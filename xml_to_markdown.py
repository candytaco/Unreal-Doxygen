#!/usr/bin/env python3
"""
xml_to_markdown.py — Doxygen XML → per-page Markdown (MSDN / Unreal Engine style)

Converts the XML output produced by Doxygen (``docs/xml/``) into individual
Markdown files — one file per function name (all overloads on the same page),
one per class — suitable for publishing to [Zensical](https://zensical.org),
MkDocs, or any other static site platform.

The output format follows the MSDN / Unreal Engine reference documentation
style described at:
https://github.com/MicrosoftDocs/microsoft-style-guide/blob/main/styleguide/developer-content/reference-documentation.md

Directory layout produced
--------------------------
::

    <output_dir>/
        index.md
        <ClassName>/
            index.md          # class overview
            <MethodName>.md   # one file per function name (all overloads combined)

Usage
-----
::

    python3 xml_to_markdown.py [--xml-dir docs/xml] [--output-dir docs/md]
    python3 xml_to_markdown.py --xml-dir path/to/xml --output-dir path/to/md

Dependencies: Python ≥ 3.9, ``lxml`` (``pip install lxml``)
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

try:
    from lxml import etree  # type: ignore[import]
except ImportError:  # pragma: no cover
    print("error: lxml is required.  Install with: pip install lxml", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _text(el: etree._Element | None, default: str = "") -> str:  # type: ignore[name-defined]
    """Return the concatenated text content of *el*, stripping excess space."""
    if el is None:
        return default
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(_text(child))
        if child.tail:
            parts.append(child.tail)
    return " ".join(p.strip() for p in parts if p.strip())


def _para_text(parent: etree._Element | None, default: str = "") -> str:  # type: ignore[name-defined]
    """Concatenate all ``<para>`` text children of *parent*."""
    if parent is None:
        return default
    paras = [_text(p) for p in parent.findall("para")]
    return "\n\n".join(p for p in paras if p)


def _ref_text(el: etree._Element) -> str:  # type: ignore[name-defined]
    """Render a ``<ref>`` element as a Markdown code-span."""
    inner = (el.text or "").strip()
    return f"`{inner}`" if inner else ""


def _description(desc_el: etree._Element | None) -> str:  # type: ignore[name-defined]
    """Convert a ``<briefdescription>`` or ``<detaileddescription>`` to Markdown."""
    if desc_el is None:
        return ""
    lines: list[str] = []
    # Use findall (direct children only) instead of iter to avoid processing
    # nested <para> elements inside <simplesect> more than once.
    for para in desc_el.findall("para"):
        # simplesect → custom section (our aliases become \par paragraphs)
        for ss in para.findall("simplesect"):
            title_el = ss.find("title")
            title = _text(title_el) if title_el is not None else ss.get("kind", "")
            body = _para_text(ss)
            if title and body:
                lines.append(f"**{title}:** {body}")
            elif body:
                lines.append(body)
            para.remove(ss)
        # remaining text in the <para>
        remaining = _text(para)
        if remaining:
            lines.append(remaining)
    return "\n\n".join(l for l in lines if l)


# ---------------------------------------------------------------------------
# Markdown page builders
# ---------------------------------------------------------------------------

def _code_block(code: str, lang: str = "cpp") -> str:
    return f"```{lang}\n{code.strip()}\n```"


def _params_table(params: list[dict[str, str]]) -> str:
    if not params:
        return ""
    rows = [
        "| Parameter | Type | Description |",
        "|-----------|------|-------------|",
    ]
    for p in params:
        name = p.get("name", "")
        typ = p.get("type", "")
        desc = p.get("desc", "")
        rows.append(f"| `{name}` | `{typ}` | {desc} |")
    return "\n".join(rows)


def _collect_params(member: etree._Element) -> list[dict[str, str]]:  # type: ignore[name-defined]
    """Return the parameter list for *member*, with descriptions filled in."""
    params: list[dict[str, str]] = []
    for param_el in member.findall("param"):
        p_type = _text(param_el.find("type"))
        p_name = _text(param_el.find("declname")) or _text(param_el.find("defname"))
        params.append({"name": p_name, "type": p_type, "desc": ""})

    # param descriptions live in <detaileddescription>/<parameterlist>
    if member.find("detaileddescription") is not None:
        for plist in member.find("detaileddescription").iter("parameterlist"):  # type: ignore[union-attr]
            if plist.get("kind") != "param":
                continue
            for pitem in plist.findall("parameteritem"):
                namelist = pitem.find("parameternamelist")
                desc_el = pitem.find("parameterdescription")
                p_name = _text(namelist.find("parametername")) if namelist is not None else ""
                p_desc = _para_text(desc_el)
                for p in params:
                    if p["name"] == p_name:
                        p["desc"] = p_desc
    return params


def _get_return_desc(member: etree._Element) -> str:  # type: ignore[name-defined]
    """Extract the ``@return`` description text from *member*."""
    if member.find("detaileddescription") is None:
        return ""
    for ss in member.find("detaileddescription").iter("simplesect"):  # type: ignore[union-attr]
        if ss.get("kind") == "return":
            return _para_text(ss)
    return ""


def _function_syntax(member: etree._Element) -> str:  # type: ignore[name-defined]
    """Build the C++ syntax string for *member*."""
    func_name = _text(member.find("name"))
    ret_type = _text(member.find("type"))
    argsstring = _text(member.find("argsstring"))
    definition = _text(member.find("definition"))
    if definition and argsstring:
        return definition + argsstring
    if definition:
        return definition
    return f"{ret_type} {func_name}{argsstring}"


def _function_page(member: etree._Element, compound_name: str) -> str:  # type: ignore[name-defined]
    """Build a Markdown page for a single (non-overloaded) member function."""
    func_name = _text(member.find("name"))
    ret_type = _text(member.find("type"))
    brief = _description(member.find("briefdescription"))
    detail = _description(member.find("detaileddescription"))
    params = _collect_params(member)
    return_desc = _get_return_desc(member)
    syntax = _function_syntax(member)

    lines: list[str] = [
        f"# {func_name}",
        "",
        f"**Class:** `{compound_name}`",
        "",
    ]
    if brief:
        lines += [brief, ""]

    lines += ["## Syntax", "", _code_block(syntax), ""]

    if params:
        lines += ["## Parameters", "", _params_table(params), ""]

    if ret_type and ret_type not in ("void", ""):
        lines += ["## Return Value", ""]
        if return_desc:
            lines += [return_desc, ""]
        else:
            lines += [f"`{ret_type}`", ""]

    if detail:
        lines += ["## Remarks", "", detail, ""]

    return "\n".join(lines)


def _function_overloads_page(
    members: list[etree._Element],  # type: ignore[name-defined]
    compound_name: str,
) -> str:
    """Build a Markdown page for a function name, grouping all overloads.

    If only one overload exists the output is identical to ``_function_page``.
    For multiple overloads each one is rendered as a ``### Overload N``
    subsection under a top-level ``## Overloads`` heading.
    """
    if len(members) == 1:
        return _function_page(members[0], compound_name)

    func_name = _text(members[0].find("name"))
    lines: list[str] = [
        f"# {func_name}",
        "",
        f"**Class:** `{compound_name}`",
        "",
        "## Overloads",
        "",
    ]

    for i, member in enumerate(members, 1):
        brief = _description(member.find("briefdescription"))
        detail = _description(member.find("detaileddescription"))
        ret_type = _text(member.find("type"))
        syntax = _function_syntax(member)
        params = _collect_params(member)
        return_desc = _get_return_desc(member)

        lines += [f"### Overload {i}", "", _code_block(syntax), ""]

        if brief:
            lines += [brief, ""]

        if params:
            lines += ["**Parameters**", "", _params_table(params), ""]

        if ret_type and ret_type not in ("void", ""):
            lines += ["**Return Value**", ""]
            if return_desc:
                lines += [return_desc, ""]
            else:
                lines += [f"`{ret_type}`", ""]

        if detail:
            lines += ["**Remarks**", "", detail, ""]

    return "\n".join(lines)


def _property_page(member: etree._Element, compound_name: str) -> str:  # type: ignore[name-defined]
    """Build a Markdown page for a UPROPERTY member variable."""
    var_name = _text(member.find("name"))
    var_type = _text(member.find("type"))
    definition = _text(member.find("definition"))
    brief = _description(member.find("briefdescription"))
    detail = _description(member.find("detaileddescription"))

    lines: list[str] = [
        f"# {var_name}",
        "",
        f"**Class:** `{compound_name}`",
        "",
    ]
    if brief:
        lines += [brief, ""]

    syntax = definition if definition else f"{var_type} {var_name}"
    lines += ["## Declaration", "", _code_block(syntax), ""]

    if detail:
        lines += ["## Remarks", "", detail, ""]

    return "\n".join(lines)


def _class_index_page(
    compound: etree._Element,  # type: ignore[name-defined]
    class_name: str,
    function_names: list[str],
    property_names: list[str],
) -> str:
    """Build the index page for a class / struct."""
    brief = _description(compound.find("briefdescription"))
    detail = _description(compound.find("detaileddescription"))
    kind = compound.get("kind", "class").capitalize()

    lines: list[str] = [
        f"# {class_name}",
        "",
        f"**Type:** {kind}",
        "",
    ]
    if brief:
        lines += [brief, ""]

    if function_names:
        lines += ["## Member Functions", ""]
        for fn in sorted(function_names):
            lines.append(f"- [{fn}]({fn}.md)")
        lines.append("")

    if property_names:
        lines += ["## Properties", ""]
        for pn in sorted(property_names):
            lines.append(f"- [{pn}]({pn}.md)")
        lines.append("")

    if detail:
        lines += ["## Remarks", "", detail, ""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Compound processor
# ---------------------------------------------------------------------------

_MEMBER_KINDS_FUNC = {"function"}
_MEMBER_KINDS_VAR = {"variable"}


def process_compound(xml_path: Path, output_dir: Path) -> str:
    """Process one Doxygen compound XML file.  Returns the compound name."""
    tree = etree.parse(str(xml_path))
    root = tree.getroot()

    compound_el = root.find("compounddef")
    if compound_el is None:
        return ""

    kind = compound_el.get("kind", "")
    if kind not in ("class", "struct", "namespace", "file"):
        return ""

    compound_name = _text(compound_el.find("compoundname"))
    # Use the last component for the directory name (strip namespace prefix)
    short_name = compound_name.rsplit("::", 1)[-1]

    class_dir = output_dir / short_name
    class_dir.mkdir(parents=True, exist_ok=True)

    # Group function members by name to merge overloads onto one page.
    # Insertion order is preserved so the page order matches the header file.
    func_groups: dict[str, list[etree._Element]] = {}  # type: ignore[name-defined]
    property_names: list[str] = []

    for member in compound_el.iter("memberdef"):
        m_kind = member.get("kind", "")
        m_prot = member.get("prot", "public")
        if m_prot not in ("public", "protected"):
            continue

        name = _text(member.find("name"))
        if not name:
            continue

        if m_kind in _MEMBER_KINDS_FUNC:
            func_groups.setdefault(name, []).append(member)
        elif m_kind in _MEMBER_KINDS_VAR:
            page = _property_page(member, compound_name)
            (class_dir / f"{name}.md").write_text(page, encoding="utf-8")
            property_names.append(name)

    for func_name, overloads in func_groups.items():
        page = _function_overloads_page(overloads, compound_name)
        (class_dir / f"{func_name}.md").write_text(page, encoding="utf-8")

    function_names = list(func_groups.keys())

    index_page = _class_index_page(
        compound_el, compound_name, function_names, property_names
    )
    (class_dir / "index.md").write_text(index_page, encoding="utf-8")

    return compound_name


# ---------------------------------------------------------------------------
# Top-level index
# ---------------------------------------------------------------------------

def _write_top_index(output_dir: Path, compound_names: list[str]) -> None:
    lines: list[str] = [
        "# API Reference",
        "",
        "Generated by [Unreal-Doxygen](https://github.com/candytaco/Unreal-Doxygen).",
        "",
        "## API Index",
        "",
    ]
    for name in sorted(compound_names):
        short = name.rsplit("::", 1)[-1]
        lines.append(f"- [{name}]({short}/index.md)")
    lines.append("")
    (output_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def convert(xml_dir: Path, output_dir: Path) -> None:
    """Convert all compound XML files in *xml_dir* to Markdown in *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)

    compound_names: list[str] = []
    xml_files = list(xml_dir.glob("*.xml"))
    if not xml_files:
        print(
            f"warning: no XML files found in {xml_dir}",
            file=sys.stderr,
        )
        return

    for xml_file in sorted(xml_files):
        if xml_file.name in ("index.xml", "Doxyfile.xml"):
            continue
        name = process_compound(xml_file, output_dir)
        if name:
            compound_names.append(name)
            print(f"  converted: {xml_file.name} → {name}")

    _write_top_index(output_dir, compound_names)
    print(f"\nWrote {len(compound_names)} compound(s) to {output_dir}/")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Convert Doxygen XML output to per-page Markdown."
    )
    parser.add_argument(
        "--xml-dir",
        metavar="DIR",
        default="docs/xml",
        help="Directory containing Doxygen XML output (default: docs/xml)",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default="docs/md",
        help="Directory to write Markdown files to (default: docs/md)",
    )
    args = parser.parse_args(argv)

    xml_dir = Path(args.xml_dir)
    output_dir = Path(args.output_dir)

    if not xml_dir.exists():
        print(f"error: XML directory not found: {xml_dir}", file=sys.stderr)
        sys.exit(1)

    convert(xml_dir, output_dir)


if __name__ == "__main__":
    main()
