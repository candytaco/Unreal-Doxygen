"""
Tests for preprocess.py — Unreal Doxygen Preprocessor.

Run with::

    pytest tests/test_preprocess.py -v
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# Make sure the repo root is on the path so we can import preprocess
sys.path.insert(0, str(Path(__file__).parent.parent))

from preprocess import (
    extract_balanced_parens,
    parse_specifiers,
    build_alias_injection,
    process_content,
    _find_preceding_doc_comment,
    _inject_into_block_comment,
    _inject_into_line_comment,
)


# ===========================================================================
# extract_balanced_parens
# ===========================================================================

class TestExtractBalancedParens:
    def test_simple(self):
        text = "(BlueprintCallable, Category = \"Combat\")"
        content, end = extract_balanced_parens(text, 0)
        assert content == "BlueprintCallable, Category = \"Combat\""
        assert end == len(text)

    def test_nested_parens(self):
        text = "(meta=(DisplayName=\"Foo\"), EditAnywhere)"
        content, end = extract_balanced_parens(text, 0)
        assert "meta=(DisplayName=\"Foo\")" in content
        assert "EditAnywhere" in content

    def test_unbalanced_raises(self):
        with pytest.raises(ValueError):
            extract_balanced_parens("(unclosed", 0)

    def test_mid_string_position(self):
        text = "UFUNCTION(BlueprintCallable)"
        paren_pos = text.index("(")
        content, end = extract_balanced_parens(text, paren_pos)
        assert content == "BlueprintCallable"
        assert end == len(text)

    def test_empty_parens(self):
        content, end = extract_balanced_parens("()", 0)
        assert content == ""
        assert end == 2


# ===========================================================================
# parse_specifiers
# ===========================================================================

class TestParseSpecifiers:
    def test_single_flag(self):
        flags, values = parse_specifiers("BlueprintCallable")
        assert flags == ["BlueprintCallable"]
        assert values == {}

    def test_multiple_flags(self):
        flags, values = parse_specifiers("BlueprintCallable, Exec")
        assert "BlueprintCallable" in flags
        assert "Exec" in flags

    def test_key_value_quoted(self):
        flags, values = parse_specifiers('BlueprintCallable, Category = "Combat"')
        assert "BlueprintCallable" in flags
        assert values.get("Category") == "Combat"

    def test_key_value_unquoted(self):
        flags, values = parse_specifiers("EditAnywhere, BlueprintReadWrite, Category=Health")
        assert values.get("Category") == "Health"

    def test_meta_block(self):
        args = 'EditDefaultsOnly, meta=(DisplayName="Weapon Name", ToolTip="Nice weapon")'
        flags, values = parse_specifiers(args)
        assert "EditDefaultsOnly" in flags
        assert values.get("meta.DisplayName") == "Weapon Name"
        assert values.get("meta.ToolTip") == "Nice weapon"

    def test_no_specifiers(self):
        flags, values = parse_specifiers("")
        assert flags == []
        assert values == {}

    def test_server_reliable(self):
        flags, values = parse_specifiers("Server, Reliable, WithValidation")
        assert "Server" in flags
        assert "Reliable" in flags


# ===========================================================================
# build_alias_injection
# ===========================================================================

class TestBuildAliasInjection:
    def test_blueprintcallable_with_category(self):
        flags = ["BlueprintCallable"]
        values = {"Category": "Combat"}
        result = build_alias_injection("UFUNCTION", flags, values)
        assert "\\ufunction" in result
        assert "\\blueprintcallable" in result
        assert "\\category{Combat}" in result

    def test_uproperty_edit_and_access(self):
        flags = ["EditAnywhere", "BlueprintReadWrite"]
        values = {"Category": "Stats"}
        result = build_alias_injection("UPROPERTY", flags, values)
        assert "\\uproperty" in result
        assert "\\editanywhere" in result
        assert "\\blueprintreadwrite" in result
        assert "\\category{Stats}" in result

    def test_unknown_specifier_ignored(self):
        # Unknown specifiers should not cause errors; they're just skipped
        flags = ["UnknownSpecifier"]
        values = {}
        result = build_alias_injection("UFUNCTION", flags, values)
        assert "\\ufunction" in result
        assert "UnknownSpecifier" not in result

    def test_meta_displayname_forwarded(self):
        flags = []
        values = {"meta.DisplayName": "My Weapon"}
        result = build_alias_injection("UPROPERTY", flags, values)
        assert "\\displayname{My Weapon}" in result

    def test_rpc_specifiers(self):
        flags = ["Server", "Reliable"]
        values = {}
        result = build_alias_injection("UFUNCTION", flags, values)
        assert "\\server" in result
        assert "\\reliable" in result


# ===========================================================================
# _find_preceding_doc_comment
# ===========================================================================

class TestFindPrecedingDocComment:
    def test_block_comment_found(self):
        content = "/** Brief description. */\nUFUNCTION(BlueprintCallable)"
        macro_start = content.index("UFUNCTION")
        result = _find_preceding_doc_comment(content, macro_start)
        assert result is not None
        start, end, kind = result
        assert kind == "block"
        assert content[start:end] == "/** Brief description. */"

    def test_no_comment(self):
        content = "int32 Foo;\nUFUNCTION(BlueprintCallable)"
        macro_start = content.index("UFUNCTION")
        assert _find_preceding_doc_comment(content, macro_start) is None

    def test_line_comment_found(self):
        content = "/// Brief description.\nUFUNCTION(BlueprintCallable)"
        macro_start = content.index("UFUNCTION")
        result = _find_preceding_doc_comment(content, macro_start)
        assert result is not None
        start, end, kind = result
        assert kind == "line"

    def test_multiline_block_comment(self):
        content = textwrap.dedent("""\
            /**
             * Brief description.
             * More details.
             */
            UFUNCTION(BlueprintCallable)
        """)
        macro_start = content.index("UFUNCTION")
        result = _find_preceding_doc_comment(content, macro_start)
        assert result is not None
        _, _, kind = result
        assert kind == "block"

    def test_plain_block_comment_not_matched(self):
        # /* comment */ (single star) should NOT match
        content = "/* not a doc comment */\nUFUNCTION(BlueprintCallable)"
        macro_start = content.index("UFUNCTION")
        assert _find_preceding_doc_comment(content, macro_start) is None


# ===========================================================================
# _inject_into_block_comment
# ===========================================================================

class TestInjectIntoBlockComment:
    def test_single_line_comment(self):
        comment = "/** Brief description. */"
        result = _inject_into_block_comment(comment, r"\blueprintcallable \category{Combat}")
        assert r"\blueprintcallable" in result
        assert result.endswith("*/")
        assert "/**" in result

    def test_multiline_comment(self):
        comment = "/**\n * Brief description.\n * More details.\n */"
        result = _inject_into_block_comment(comment, r"\blueprintcallable")
        assert r"\blueprintcallable" in result
        assert result.endswith("*/")

    def test_injection_before_closing(self):
        comment = "/** foo */"
        result = _inject_into_block_comment(comment, "INJECT")
        # Injection should appear before */
        close = result.index("*/")
        inject = result.index("INJECT")
        assert inject < close


# ===========================================================================
# _inject_into_line_comment
# ===========================================================================

class TestInjectIntoLineComment:
    def test_appends_new_line(self):
        content = "/// Brief description.\nUFUNCTION()"
        comment_end = content.index("\n")  # end of the /// line (exclusive)
        result = _inject_into_line_comment(content, comment_end, r"\blueprintcallable")
        assert "/// " + r"\blueprintcallable" in result


# ===========================================================================
# process_content — integration tests
# ===========================================================================

class TestProcessContent:
    def test_blueprintcallable_injected(self):
        source = textwrap.dedent("""\
            /** @brief Applies damage. */
            UFUNCTION(BlueprintCallable, Category = "Combat")
            void ApplyDamage(float Amount);
        """)
        result = process_content(source)
        assert r"\blueprintcallable" in result
        assert r"\category{Combat}" in result

    def test_macro_commented_out(self):
        source = textwrap.dedent("""\
            /** @brief Brief. */
            UFUNCTION(BlueprintCallable)
            void Foo();
        """)
        result = process_content(source)
        # The original macro should be commented out
        assert "// UFUNCTION(" in result
        # The actual declaration should still be present
        assert "void Foo();" in result

    def test_uproperty_injection(self):
        source = textwrap.dedent("""\
            /** @brief Max health. */
            UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Stats")
            float MaxHealth;
        """)
        result = process_content(source)
        assert r"\uproperty" in result
        assert r"\editanywhere" in result
        assert r"\blueprintreadwrite" in result
        assert r"\category{Stats}" in result

    def test_no_comment_still_comments_out_macro(self):
        source = "UPROPERTY(EditAnywhere)\nfloat Health;\n"
        result = process_content(source)
        assert "// UPROPERTY(" in result
        assert "float Health;" in result

    def test_multiline_macro_commented(self):
        source = textwrap.dedent("""\
            /** @brief A function. */
            UFUNCTION(
                BlueprintCallable,
                Category = "Test"
            )
            void Bar();
        """)
        result = process_content(source)
        assert r"\blueprintcallable" in result
        # All macro lines should be commented out
        for line in result.splitlines():
            stripped = line.strip()
            if "UFUNCTION" in stripped or "BlueprintCallable" in stripped or "Category" in stripped:
                assert stripped.startswith("//"), (
                    f"Expected macro line to be commented out: {stripped!r}"
                )

    def test_uclass_with_blueprintable(self):
        source = textwrap.dedent("""\
            /** @brief Base class. */
            UCLASS(Blueprintable, BlueprintType)
            class AMyActor : public AActor
            {
            };
        """)
        result = process_content(source)
        assert r"\blueprintable" in result
        assert r"\blueprinttype" in result

    def test_server_rpc_injection(self):
        source = textwrap.dedent("""\
            /** @brief Server RPC. */
            UFUNCTION(Server, Reliable)
            void Server_Foo();
        """)
        result = process_content(source)
        assert r"\server" in result
        assert r"\reliable" in result

    def test_meta_displayname_injected(self):
        source = textwrap.dedent("""\
            /** @brief My property. */
            UPROPERTY(EditDefaultsOnly, meta = (DisplayName = "Fancy Name"))
            FString Name;
        """)
        result = process_content(source)
        assert r"\displayname{Fancy Name}" in result

    def test_no_docstring_does_not_crash(self):
        # Macros without preceding doc-comments should be processed without errors
        source = textwrap.dedent("""\
            UPROPERTY(EditAnywhere)
            float Health;
            UFUNCTION(BlueprintCallable)
            void Foo();
        """)
        result = process_content(source)
        assert "// UPROPERTY(" in result
        assert "// UFUNCTION(" in result

    def test_fixture_ufunction(self):
        """Process the ufunction fixture file without errors."""
        fixture = Path(__file__).parent / "fixtures" / "sample_ufunction.h"
        content = fixture.read_text(encoding="utf-8")
        result = process_content(content)
        assert r"\blueprintcallable" in result
        assert r"\blueprintpure" in result
        assert r"\server" in result
        assert r"\reliable" in result
        assert r"\exec" in result

    def test_fixture_uproperty(self):
        """Process the uproperty fixture file without errors."""
        fixture = Path(__file__).parent / "fixtures" / "sample_uproperty.h"
        content = fixture.read_text(encoding="utf-8")
        result = process_content(content)
        assert r"\blueprintreadwrite" in result
        assert r"\blueprintreadonly" in result
        assert r"\editanywhere" in result
        assert r"\transient" in result
        assert r"\savegame" in result

    def test_fixture_uclass(self):
        """Process the uclass fixture file without errors."""
        fixture = Path(__file__).parent / "fixtures" / "sample_uclass.h"
        content = fixture.read_text(encoding="utf-8")
        result = process_content(content)
        assert r"\blueprintable" in result
        assert r"\blueprintassignable" in result
        assert r"\server" in result
