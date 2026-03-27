#!/usr/bin/env python3
"""
Unreal Doxygen Preprocessor

This script is a Doxygen INPUT_FILTER that processes Unreal Engine C++ source
files.  For every Unreal reflection macro found (UPROPERTY, UFUNCTION, UCLASS,
USTRUCT, UENUM, UDELEGATE) it:

  1. Parses the specifier list inside the macro's parentheses.
  2. Maps each specifier to the matching Doxygen alias defined in the Doxyfile.
  3. Injects the alias commands into the immediately-preceding documentation
     comment so Doxygen can describe how the item behaves in Blueprint.
  4. Comments out the macro line(s) so that Doxygen correctly attaches the
     documentation comment to the C++ declaration that follows.

Usage
-----
As a Doxygen INPUT_FILTER (set in Doxyfile)::

    INPUT_FILTER = "python3 preprocess.py"

Or via FILTER_PATTERNS for per-extension control::

    FILTER_PATTERNS = *.h="python3 preprocess.py" \\
                      *.hpp="python3 preprocess.py" \\
                      *.cpp="python3 preprocess.py"

Standalone::

    python3 preprocess.py <input_file>
    python3 preprocess.py <input_file> -o <output_file>
"""

from __future__ import annotations

import re
import sys
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Recognised Unreal reflection macros
# ---------------------------------------------------------------------------
UNREAL_MACROS: tuple[str, ...] = (
    "UPROPERTY",
    "UFUNCTION",
    "UCLASS",
    "USTRUCT",
    "UENUM",
    "UDELEGATE",
    "UMETA",
    "UPARAM",
)

# ---------------------------------------------------------------------------
# Bare (flag-style) specifier → Doxygen alias
# ---------------------------------------------------------------------------
SPECIFIER_ALIASES: dict[str, str] = {
    # Blueprint property access
    "BlueprintReadWrite":           r"\blueprintreadwrite",
    "BlueprintReadOnly":            r"\blueprintreadonly",
    "BlueprintNativeOnly":          r"\blueprintnativeonly",
    "BlueprintAssignable":          r"\blueprintassignable",
    "BlueprintAuthorityOnly":       r"\blueprintauthorityonly",
    "BlueprintCosmetic":            r"\blueprintcosmetic",
    # Blueprint function
    "BlueprintCallable":            r"\blueprintcallable",
    "BlueprintPure":                r"\blueprintpure",
    "BlueprintImplementableEvent":  r"\blueprintimplementableevent",
    "BlueprintNativeEvent":         r"\blueprintnativeevent",
    # Property edit / visibility
    "EditAnywhere":                 r"\editanywhere",
    "EditDefaultsOnly":             r"\editdefaultsonly",
    "EditInstanceOnly":             r"\editinstanceonly",
    "VisibleAnywhere":              r"\visibleanywhere",
    "VisibleDefaultsOnly":          r"\visibledefaultsonly",
    "VisibleInstanceOnly":          r"\visibleinstanceonly",
    "EditFixedSize":                r"\editfixedsize",
    "EditInline":                   r"\editinline",
    # RPC / networking
    "Exec":                         r"\exec",
    "Server":                       r"\server",
    "Client":                       r"\client",
    "NetMulticast":                 r"\netmulticast",
    "Reliable":                     r"\reliable",
    "Unreliable":                   r"\unreliable",
    # Serialisation
    "Transient":                    r"\transient",
    "SaveGame":                     r"\savegame",
    "Config":                       r"\config",
    "GlobalConfig":                 r"\globalconfig",
    # Class specifiers
    "Abstract":                     r"\abstract_class",
    "Blueprintable":                r"\blueprintable",
    "NotBlueprintable":             r"\notblueprintable",
    "BlueprintType":                r"\blueprinttype",
    "NotBlueprintType":             r"\notblueprinttype",
    "Deprecated":                   r"\deprecated_ue",
}

# ---------------------------------------------------------------------------
# key=value specifier → Doxygen alias prefix  (value becomes the {arg})
# ---------------------------------------------------------------------------
VALUED_SPECIFIER_ALIASES: dict[str, str] = {
    "Category":         r"\category",
    "DisplayName":      r"\displayname",
    "ToolTip":          r"\uetooltip",
    "Keywords":         r"\uekeywords",
    "BlueprintSetter":  r"\blueprintsetter",
    "BlueprintGetter":  r"\blueprintgetter",
}

# meta=(key=value) keys forwarded to aliases
META_KEY_ALIASES: dict[str, str] = {
    "DisplayName": r"\displayname",
    "ToolTip":     r"\uetooltip",
    "Keywords":    r"\uekeywords",
}


# ===========================================================================
# Low-level helpers
# ===========================================================================

def extract_balanced_parens(text: str, start: int) -> tuple[str, int]:
    """Return *(content, end_pos)* for the balanced ``(…)`` region.

    *start* must point at the opening ``(``.  *end_pos* is the index of the
    character **after** the closing ``)``.

    Raises ``ValueError`` when parentheses are unbalanced.
    """
    assert text[start] == "(", f"Expected '(' at position {start}, got {text[start]!r}"
    depth = 0
    in_string = False
    escape_next = False
    i = start
    while i < len(text):
        ch = text[i]
        if escape_next:
            escape_next = False
        elif ch == "\\" and in_string:
            escape_next = True
        elif ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return text[start + 1 : i], i + 1
        i += 1
    raise ValueError(f"Unbalanced parentheses starting at position {start}")


def _tokenize_args(text: str) -> list[str]:
    """Split *text* by top-level commas (respects strings and parentheses)."""
    tokens: list[str] = []
    current: list[str] = []
    depth = 0
    in_string = False
    for ch in text:
        if ch == '"':
            in_string = not in_string
            current.append(ch)
        elif in_string:
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            tokens.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return tokens


# ===========================================================================
# Specifier parsing
# ===========================================================================

def parse_specifiers(args: str) -> tuple[list[str], dict[str, str]]:
    """Parse a macro argument string into *(flags, values)*.

    ``flags`` is an ordered list of bare specifier names
    (e.g. ``['BlueprintCallable', 'Exec']``).

    ``values`` maps key → value for ``key=value`` specifiers
    (e.g. ``{'Category': 'Combat'}``) and
    ``meta.<key>`` → value for ``meta=(…)`` entries.
    """
    flags: list[str] = []
    values: dict[str, str] = {}

    # Extract and remove meta=(…) blocks first
    meta_pattern = re.compile(r"\bmeta\s*=\s*\(([^)]*)\)", re.IGNORECASE)
    for meta_match in meta_pattern.finditer(args):
        meta_content = meta_match.group(1)
        # Quoted values
        for kv in re.finditer(r'(\w+)\s*=\s*"([^"]*)"', meta_content):
            values[f"meta.{kv.group(1)}"] = kv.group(2)
        # Unquoted values
        for kv in re.finditer(r"(\w+)\s*=\s*([^,\s\"]+)", meta_content):
            key = f"meta.{kv.group(1)}"
            if key not in values:
                values[key] = kv.group(2).strip()
    args = meta_pattern.sub("", args)

    for token in _tokenize_args(args):
        token = token.strip()
        if not token:
            continue
        # key="value"
        kv = re.match(r'^(\w+)\s*=\s*"([^"]*)"$', token)
        if kv:
            values[kv.group(1)] = kv.group(2)
            continue
        # key=value  (unquoted)
        kv = re.match(r"^(\w+)\s*=\s*(.+)$", token)
        if kv:
            values[kv.group(1)] = kv.group(2).strip().strip('"')
            continue
        # bare specifier
        if re.match(r"^\w+$", token):
            flags.append(token)

    return flags, values


# ===========================================================================
# Alias injection string builder
# ===========================================================================

def build_alias_injection(
    macro_name: str,
    flags: list[str],
    values: dict[str, str],
) -> str:
    """Return a string of Doxygen alias commands to inject into a doc-comment."""
    parts: list[str] = [f"\\{macro_name.lower()}"]

    for flag in flags:
        alias = SPECIFIER_ALIASES.get(flag)
        if alias:
            parts.append(alias)

    for key, val in values.items():
        if key.startswith("meta."):
            meta_key = key[5:]
            meta_alias = META_KEY_ALIASES.get(meta_key)
            if meta_alias:
                parts.append(f"{meta_alias}{{{val}}}")
        else:
            alias = VALUED_SPECIFIER_ALIASES.get(key)
            if alias:
                parts.append(f"{alias}{{{val}}}")

    return " ".join(parts)


# ===========================================================================
# Comment detection
# ===========================================================================

def _find_preceding_doc_comment(
    content: str,
    macro_start: int,
) -> tuple[int, int, str] | None:
    """Find the documentation comment immediately preceding *macro_start*.

    Returns ``(comment_start, comment_end, kind)`` where *kind* is
    ``'block'`` (``/** … */``) or ``'line'`` (``/// …`` / ``//! …``).
    Returns ``None`` when no doc-comment is found directly before the macro.
    """
    # Walk backwards, skipping blank lines / spaces
    pos = macro_start - 1
    while pos >= 0 and content[pos] in " \t\r\n":
        pos -= 1

    if pos < 1:
        return None

    # ---- block comment -------------------------------------------------------
    if content[pos - 1 : pos + 1] == "*/":
        end = pos + 1  # exclusive end of comment text
        start = content.rfind("/*", 0, pos - 1)
        if start == -1:
            return None
        if start + 2 < len(content) and content[start + 2] in ("*", "!"):
            return (start, end, "block")
        return None

    # ---- line comment (/// or //!) -------------------------------------------
    line_start = content.rfind("\n", 0, pos)
    line_start = line_start + 1 if line_start != -1 else 0
    line = content[line_start : pos + 1].strip()

    if line.startswith("///") or line.startswith("//!"):
        comment_end = pos + 1
        comment_start = line_start
        # Walk backwards through consecutive doc-comment lines
        while True:
            if comment_start == 0:
                break
            prev_nl = content.rfind("\n", 0, comment_start - 1)
            prev_line_start = prev_nl + 1 if prev_nl != -1 else 0
            prev_line = content[prev_line_start : comment_start - 1].strip()
            if prev_line.startswith("///") or prev_line.startswith("//!"):
                comment_start = prev_line_start
            else:
                break
        return (comment_start, comment_end, "line")

    return None


# ===========================================================================
# Injection helpers
# ===========================================================================

def _inject_into_block_comment(comment: str, injection: str) -> str:
    """Insert *injection* on a new line before the closing ``*/``."""
    close = comment.rfind("*/")
    if close == -1:
        return comment  # malformed – leave unchanged

    prev_newline = comment.rfind("\n", 0, close)

    if prev_newline == -1:
        # Single-line comment: /** brief */ → inject on a new line before */
        before = comment[:close].rstrip()
        return before + f"\n * {injection}\n " + comment[close:]

    # Multi-line comment: derive indentation from the line that holds */
    # e.g. "     */" → ws = "     "
    closing_prefix = comment[prev_newline + 1 : close]
    ws = re.match(r"^(\s*)", closing_prefix).group(1)  # type: ignore[union-attr]

    # Insert "<ws>* injection" between the last content line and the */ line.
    # ws comes from the leading whitespace of the "     */" closing line,
    # so "     " + "* " matches the indentation of all other " * " content lines.
    return (
        comment[:prev_newline]
        + f"\n{ws}* {injection}"
        + "\n"
        + comment[prev_newline + 1 :]
    )


def _inject_into_line_comment(content: str, comment_end: int, injection: str) -> str:
    """Append an extra ``/// injection`` line after the last comment line."""
    # Determine the indentation of the last comment line
    last_nl = content.rfind("\n", 0, comment_end)
    if last_nl == -1:
        indent = ""
    else:
        line = content[last_nl + 1 : comment_end]
        indent = re.match(r"^(\s*)", line).group(1)  # type: ignore[union-attr]
    new_line = f"\n{indent}/// {injection}"
    return content[:comment_end] + new_line + content[comment_end:]


# ===========================================================================
# Main processing
# ===========================================================================

def _build_comment_ranges(content: str) -> list[tuple[int, int]]:
    """Return a sorted list of ``(start, end)`` ranges for all comment spans.

    Both ``//`` line comments and ``/* … */`` block comments are included.
    String and character literals are skipped so that ``//`` or ``/*`` inside
    quoted text is not misidentified as a comment start.
    Ranges are sorted in ascending order by start position (guaranteed by the
    sequential left-to-right scan).
    The ranges use exclusive end indices (Python slice convention).
    """
    ranges: list[tuple[int, int]] = []
    i = 0
    n = len(content)
    while i < n:
        ch = content[i]

        # Skip string and character literals (handles backslash escape sequences)
        if ch == '"':
            i += 1
            while i < n:
                if content[i] == "\\":
                    i += 2
                elif content[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue

        # Skip character literals (handles backslash escape sequences)
        if ch == "'":
            i += 1
            while i < n:
                if content[i] == "\\":
                    i += 2
                elif content[i] == "'":
                    i += 1
                    break
                else:
                    i += 1
            continue

        if ch == "/" and i + 1 < n:
            if content[i + 1] == "/":
                # Line comment: extends to end of line
                end = content.find("\n", i + 2)
                end = end if end != -1 else n
                ranges.append((i, end))
                i = end
                continue
            if content[i + 1] == "*":
                # Block comment: extends to closing */
                end = content.find("*/", i + 2)
                end = end + 2 if end != -1 else n
                ranges.append((i, end))
                i = end
                continue
        i += 1
    return ranges


def _in_comment(pos: int, comment_ranges: list[tuple[int, int]]) -> bool:
    """Return True if *pos* falls inside any of the precomputed comment ranges.

    Uses binary search (O(log n)) since *comment_ranges* is sorted by start.
    """
    if not comment_ranges:
        return False
    # Binary search for the rightmost range whose start <= pos.
    lo, hi = 0, len(comment_ranges)
    while lo < hi:
        mid = (lo + hi) // 2
        if comment_ranges[mid][0] <= pos:
            lo = mid + 1
        else:
            hi = mid
    # lo - 1 is the index of the rightmost range with start <= pos (if any).
    if lo > 0:
        start, end = comment_ranges[lo - 1]
        return start <= pos < end
    return False


def process_content(content: str) -> str:
    """Process C++ file content and return the filtered version for Doxygen."""

    # Anchor to the start of a line (after optional horizontal whitespace) so
    # that a macro name mentioned inside a comment body or a string literal is
    # not mistaken for a real macro invocation.  We use [ \t]* instead of \s*
    # to match only spaces and tabs (normal C++ indentation) and avoid
    # consuming newlines that would skip blank lines between constructs.
    macro_re = re.compile(
        r"^[ \t]*(" + "|".join(re.escape(m) for m in UNREAL_MACROS) + r")\s*\(",
        re.MULTILINE,
    )

    # Pre-compute comment ranges so we can skip matches that fall inside them.
    comment_ranges = _build_comment_ranges(content)

    # Collect all macro spans so we can process them without offset drift.
    # We do a single reverse-order edit pass.
    class _MacroSpan:
        __slots__ = ("name", "args", "span_start", "span_end")

        def __init__(self, name: str, args: str, span_start: int, span_end: int) -> None:
            self.name = name
            self.args = args
            self.span_start = span_start
            self.span_end = span_end

    spans: list[_MacroSpan] = []
    for m in macro_re.finditer(content):
        # Skip matches that fall inside a comment (e.g. a doc comment that
        # mentions UFUNCTION in its body, or a macro inside a block comment).
        if _in_comment(m.start(), comment_ranges):
            continue
        paren_pos = m.end() - 1  # points at '('
        try:
            args, end = extract_balanced_parens(content, paren_pos)
        except ValueError:
            continue
        spans.append(_MacroSpan(m.group(1), args, m.start(), end))

    # Process in reverse order so that earlier edits don't shift later offsets.
    for span in reversed(spans):
        flags, values = parse_specifiers(span.args)
        injection = build_alias_injection(span.name, flags, values)

        # 1. Inject aliases into the preceding doc-comment (if any)
        comment_info = _find_preceding_doc_comment(content, span.span_start)
        if comment_info and injection:
            c_start, c_end, kind = comment_info
            if kind == "block":
                original_comment = content[c_start:c_end]
                new_comment = _inject_into_block_comment(original_comment, injection)
                content = content[:c_start] + new_comment + content[c_end:]
                # Recalculate span offsets after the comment edit
                delta = len(new_comment) - len(original_comment)
                span.span_start += delta
                span.span_end += delta
            else:  # line
                old_len = len(content)
                content = _inject_into_line_comment(content, c_end, injection)
                delta = len(content) - old_len
                span.span_start += delta
                span.span_end += delta

        # 2. Comment out the macro
        macro_text = content[span.span_start : span.span_end]
        commented = "// " + macro_text.replace("\n", "\n// ")
        content = content[: span.span_start] + commented + content[span.span_end :]

    return content


# ===========================================================================
# CLI entry point
# ===========================================================================

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Unreal Doxygen Preprocessor — inject Doxygen aliases from Unreal "
            "reflection macros and comment them out for Doxygen processing."
        )
    )
    parser.add_argument("input", help="Input C++ source file")
    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    args = parser.parse_args(argv)

    try:
        content = Path(args.input).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    processed = process_content(content)

    if args.output:
        Path(args.output).write_text(processed, encoding="utf-8")
    else:
        sys.stdout.write(processed)


if __name__ == "__main__":
    main()
