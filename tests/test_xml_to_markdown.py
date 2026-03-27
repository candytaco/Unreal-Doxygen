"""
Tests for XML to markdown.py — Doxygen XML → Markdown converter.

Run with::

    pytest tests/test_xml_to_markdown.py -v
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from lxml import etree

# Make sure the repo root is on the path so we can import the converter module.
sys.path.insert(0, str(Path(__file__).parent.parent))

# The module name has a space, so we must import it via importlib.
import importlib

_mod = importlib.import_module("XML to markdown")
_class_declaration = _mod._class_declaration
_members_table = _mod._members_table
_class_index_page = _mod._class_index_page
_function_page = _mod._function_page
_function_overloads_page = _mod._function_overloads_page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_compound(
    kind: str = "class",
    name: str = "MyClass",
    base: str | None = "AActor",
    brief: str = "Brief description.",
    detail: str = "",
) -> etree._Element:
    """Build a minimal ``<compounddef>`` element for testing."""
    el = etree.Element("compounddef", kind=kind)
    cn = etree.SubElement(el, "compoundname")
    cn.text = name
    if base:
        br = etree.SubElement(el, "basecompoundref", prot="public", virt="non-virtual")
        br.text = base
    bd = etree.SubElement(el, "briefdescription")
    if brief:
        p = etree.SubElement(bd, "para")
        p.text = brief
    dd = etree.SubElement(el, "detaileddescription")
    if detail:
        p = etree.SubElement(dd, "para")
        p.text = detail
    return el


def _make_member(
    name: str = "MyFunc",
    ret: str = "void",
    args: str = "()",
    brief: str = "Does something.",
    detail: str = "",
) -> etree._Element:
    """Build a minimal ``<memberdef kind='function'>`` element for testing."""
    el = etree.Element("memberdef", kind="function", prot="public")
    n = etree.SubElement(el, "name")
    n.text = name
    t = etree.SubElement(el, "type")
    t.text = ret
    a = etree.SubElement(el, "argsstring")
    a.text = args
    d = etree.SubElement(el, "definition")
    d.text = f"{ret} {name}"
    bd = etree.SubElement(el, "briefdescription")
    if brief:
        p = etree.SubElement(bd, "para")
        p.text = brief
    dd = etree.SubElement(el, "detaileddescription")
    if detail:
        p = etree.SubElement(dd, "para")
        p.text = detail
    return el


# ===========================================================================
# _class_declaration
# ===========================================================================

class TestClassDeclaration:
    def test_class_with_base(self):
        compound = _make_compound(kind="class", name="AMyActor", base="AActor")
        result = _class_declaration(compound, "AMyActor")
        assert result == "class AMyActor : public AActor"

    def test_struct_no_base(self):
        compound = _make_compound(kind="struct", name="FMyStruct", base=None)
        result = _class_declaration(compound, "FMyStruct")
        assert result == "struct FMyStruct"

    def test_strips_namespace_prefix(self):
        compound = _make_compound(kind="class", name="NS::MyClass", base=None)
        result = _class_declaration(compound, "NS::MyClass")
        assert result == "class MyClass"

    def test_multiple_bases(self):
        el = etree.Element("compounddef", kind="class")
        cn = etree.SubElement(el, "compoundname")
        cn.text = "MyClass"
        b1 = etree.SubElement(el, "basecompoundref", prot="public", virt="non-virtual")
        b1.text = "Base1"
        b2 = etree.SubElement(el, "basecompoundref", prot="private", virt="non-virtual")
        b2.text = "Base2"
        result = _class_declaration(el, "MyClass")
        assert "public Base1" in result
        assert "private Base2" in result


# ===========================================================================
# _members_table
# ===========================================================================

class TestMembersTable:
    def test_method_table_headers(self):
        entries = [("Foo", "Does foo."), ("Bar", "Does bar.")]
        result = _members_table(entries, "Method")
        assert "| Method | Description |" in result

    def test_property_table_headers(self):
        entries = [("Health", "Current health.")]
        result = _members_table(entries, "Property")
        assert "| Property | Description |" in result

    def test_links_generated(self):
        entries = [("ApplyDamage", "Applies damage.")]
        result = _members_table(entries, "Method")
        assert "[ApplyDamage](ApplyDamage.md)" in result

    def test_descriptions_included(self):
        entries = [("Heal", "Restores health.")]
        result = _members_table(entries, "Method")
        assert "Restores health." in result

    def test_empty_returns_empty_string(self):
        assert _members_table([], "Method") == ""


# ===========================================================================
# _class_index_page — structure follows style guide
# ===========================================================================

class TestClassIndexPage:
    def _build(self, func_briefs=None, prop_briefs=None, detail=""):
        compound = _make_compound(
            kind="class",
            name="AMyActor",
            base="AActor",
            brief="A sample actor.",
            detail=detail,
        )
        return _class_index_page(
            compound,
            "AMyActor",
            func_briefs or {},
            prop_briefs or {},
        )

    def test_title_is_class_name(self):
        page = self._build()
        assert page.startswith("# AMyActor")

    def test_summary_before_syntax(self):
        page = self._build()
        summary_pos = page.index("A sample actor.")
        syntax_pos = page.index("## Syntax")
        assert summary_pos < syntax_pos

    def test_syntax_section_present(self):
        page = self._build()
        assert "## Syntax" in page

    def test_syntax_contains_class_declaration(self):
        page = self._build()
        assert "class AMyActor" in page
        assert "AActor" in page

    def test_syntax_before_remarks(self):
        page = self._build(detail="Some extra notes.")
        syntax_pos = page.index("## Syntax")
        remarks_pos = page.index("## Remarks")
        assert syntax_pos < remarks_pos

    def test_remarks_before_methods(self):
        page = self._build(
            func_briefs={"Foo": "Does foo."},
            detail="Detailed remarks.",
        )
        remarks_pos = page.index("## Remarks")
        methods_pos = page.index("## Methods")
        assert remarks_pos < methods_pos

    def test_methods_in_table_not_list(self):
        page = self._build(func_briefs={"ApplyDamage": "Applies damage."})
        assert "## Methods" in page
        # Must be a table (pipe syntax), not a plain bullet list
        assert "| Method | Description |" in page
        assert "[ApplyDamage](ApplyDamage.md)" in page
        # Must NOT be a bullet list item
        assert "- [ApplyDamage]" not in page

    def test_method_brief_in_table(self):
        page = self._build(func_briefs={"Heal": "Restores health."})
        assert "Restores health." in page

    def test_properties_in_table(self):
        page = self._build(prop_briefs={"Health": "Current HP."})
        assert "## Properties" in page
        assert "| Property | Description |" in page
        assert "[Health](Health.md)" in page

    def test_no_member_functions_omits_methods_section(self):
        page = self._build()
        assert "## Methods" not in page

    def test_no_properties_omits_properties_section(self):
        page = self._build()
        assert "## Properties" not in page

    def test_no_remarks_omits_remarks_section(self):
        page = self._build(detail="")
        assert "## Remarks" not in page

    def test_no_type_label(self):
        # The old "**Type:** Class" line should no longer appear
        page = self._build()
        assert "**Type:**" not in page


# ===========================================================================
# _function_page — title includes "method"
# ===========================================================================

class TestFunctionPageTitle:
    def test_title_ends_with_method(self):
        member = _make_member(name="ApplyDamage")
        page = _function_page(member, "AMyActor")
        assert page.startswith("# ApplyDamage method")

    def test_title_not_bare_name(self):
        member = _make_member(name="Heal")
        page = _function_page(member, "AMyActor")
        # Must include the word "method" after the function name
        assert "# Heal method" in page
        # Must NOT be a bare "# Heal" heading (with or without trailing newline)
        assert not any(
            line == "# Heal" for line in page.splitlines()
        )

    def test_structure_summary_syntax_remarks(self):
        member = _make_member(name="Foo", detail="Extra notes.")
        page = _function_page(member, "AMyActor")
        brief_pos = page.index("Does something.")
        syntax_pos = page.index("## Syntax")
        remarks_pos = page.index("## Remarks")
        assert brief_pos < syntax_pos < remarks_pos


# ===========================================================================
# _function_overloads_page — title includes "method"
# ===========================================================================

class TestFunctionOverloadsPageTitle:
    def test_single_overload_delegates_to_function_page(self):
        member = _make_member(name="Fire")
        page = _function_overloads_page([member], "AWeapon")
        assert page.startswith("# Fire method")

    def test_multi_overload_title_ends_with_method(self):
        m1 = _make_member(name="Fire", args="()", brief="No-arg fire.")
        m2 = _make_member(name="Fire", args="(float Strength)", brief="Strength fire.")
        page = _function_overloads_page([m1, m2], "AWeapon")
        assert page.startswith("# Fire method")
        assert "## Overloads" in page
