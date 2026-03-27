#!/usr/bin/env python3
"""
XML to markdown.py — Doxygen XML → per-page Markdown (MSDN / Unreal Engine style)

Converts the XML output produced by Doxygen (``docs/xml/``) into individual
Markdown files — one file per function name (all overloads on the same page),
one per class — suitable for publishing to `Zensical <https://zensical.org>`_,
MkDocs, or any other static site platform.

The output format follows the MSDN / Unreal Engine reference documentation
style described at:
https://github.com/MicrosoftDocs/microsoft-style-guide/blob/main/styleguide/developer-content/reference-documentation.md

Directory layout produced
--------------------------
::

    <output_dir>/
        index.md
        <PluginName>/
            index.md          # plugin overview
            <ClassName>/
                index.md          # class overview
                <MethodName>.md   # one file per function name (all overloads combined)

Usage
-----
::

    python3 "XML to markdown.py" [--xml-dir docs/xml] [--output-dir docs/md]
    python3 "XML to markdown.py" --xml-dir path/to/xml --output-dir path/to/md

Dependencies: Python >= 3.9, ``lxml`` (``pip install lxml``)
"""

from __future__ import annotations

import argparse
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

def _getText(element: etree._Element | None, default: str = "") -> str:  # type: ignore[name-defined]
	"""Return the concatenated text content of element, stripping excess whitespace."""
	if element is None:
		return default
	parts: list[str] = []
	if element.text:
		parts.append(element.text)
	for child in element:
		parts.append(_getText(child))
		if child.tail:
			parts.append(child.tail)
	return " ".join(part.strip() for part in parts if part.strip())


def _paraText(parentElement: etree._Element | None, default: str = "") -> str:  # type: ignore[name-defined]
	"""Concatenate all ``<para>`` text children of parentElement."""
	if parentElement is None:
		return default
	paragraphs = [_getText(paragraph) for paragraph in parentElement.findall("para")]
	return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def _description(descriptionElement: etree._Element | None) -> str:  # type: ignore[name-defined]
	"""Convert a ``<briefdescription>`` or ``<detaileddescription>`` to Markdown.

	Note: ``<simplesect kind="return">`` elements are intentionally skipped here
	and left in the tree for ``_getReturnDescription`` to handle separately.
	"""
	if descriptionElement is None:
		return ""
	lines: list[str] = []
	# Use findall (direct children only) to avoid re-processing nested <para>
	# elements inside <simplesect> more than once.
	for paragraph in descriptionElement.findall("para"):
		for simplesect in paragraph.findall("simplesect"):
			# Return descriptions are rendered in their own section; skip them here.
			if simplesect.get("kind") == "return":
				continue
			titleElement = simplesect.find("title")
			title = _getText(titleElement) if titleElement is not None else simplesect.get("kind", "")
			body = _paraText(simplesect)
			if title and body:
				lines.append("**{}:** {}".format(title, body))
			elif body:
				lines.append(body)
			paragraph.remove(simplesect)
		remaining = _getText(paragraph)
		if remaining:
			lines.append(remaining)
	return "\n\n".join(line for line in lines if line)


# ---------------------------------------------------------------------------
# Markdown page builders
# ---------------------------------------------------------------------------

def _codeBlock(code: str, lang: str = "cpp") -> str:
	return "```{}\n{}\n```".format(lang, code.strip())


def _paramsTable(parameterList: list[dict[str, str]]) -> str:
	if not parameterList:
		return ""
	rows = [
		"| Parameter | Type | Description |",
		"|-----------|------|-------------|",
	]
	for parameter in parameterList:
		name = parameter.get("name", "")
		parameterType = parameter.get("type", "")
		description = parameter.get("desc", "")
		rows.append("| `{}` | `{}` | {} |".format(name, parameterType, description))
	return "\n".join(rows)


def _collectParams(memberElement: etree._Element) -> list[dict[str, str]]:  # type: ignore[name-defined]
	"""Return the parameter list for memberElement, with descriptions filled in."""
	parameterList: list[dict[str, str]] = []
	for paramElement in memberElement.findall("param"):
		parameterType = _getText(paramElement.find("type"))
		parameterName = _getText(paramElement.find("declname")) or _getText(paramElement.find("defname"))
		parameterList.append({"name": parameterName, "type": parameterType, "desc": ""})

	# Parameter descriptions live in <detaileddescription>/<parameterlist>.
	detailedDescription = memberElement.find("detaileddescription")
	if detailedDescription is not None:
		for parameterListElement in detailedDescription.iter("parameterlist"):  # type: ignore[union-attr]
			if parameterListElement.get("kind") != "param":
				continue
			for parameterItem in parameterListElement.findall("parameteritem"):
				nameList = parameterItem.find("parameternamelist")
				descriptionElement = parameterItem.find("parameterdescription")
				parameterName = _getText(nameList.find("parametername")) if nameList is not None else ""
				parameterDescription = _paraText(descriptionElement)
				for parameter in parameterList:
					if parameter["name"] == parameterName:
						parameter["desc"] = parameterDescription
	return parameterList


def _getReturnDescription(memberElement: etree._Element) -> str:  # type: ignore[name-defined]
	"""Extract the ``@return`` description text from memberElement."""
	detailedDescription = memberElement.find("detaileddescription")
	if detailedDescription is None:
		return ""
	for simplesect in detailedDescription.iter("simplesect"):
		if simplesect.get("kind") == "return":
			return _paraText(simplesect)
	return ""


def _functionSyntax(memberElement: etree._Element) -> str:  # type: ignore[name-defined]
	"""Build the C++ syntax string for memberElement."""
	functionName = _getText(memberElement.find("name"))
	returnType = _getText(memberElement.find("type"))
	argumentsString = _getText(memberElement.find("argsstring"))
	definition = _getText(memberElement.find("definition"))
	if definition and argumentsString:
		return definition + argumentsString
	if definition:
		return definition
	return "{} {}{}".format(returnType, functionName, argumentsString)


def _parseParTitleSegments(titleText: str) -> list[tuple[str, str]]:
	"""Parse a combined par-title string into (sectionTitle, sectionContent) pairs.

	The doxygen preprocessor combines multiple ``\\par`` entries into a single
	``<simplesect kind="par">`` whose title has the format::

	    Title1\\n Content1\\n \\par Title2\\n Content2\\n ...

	where ``\\n`` and ``\\par`` are literal two-character sequences in the XML
	text content (not actual newline or Doxygen command characters).
	"""
	segments = titleText.split("\\n \\par ")
	result: list[tuple[str, str]] = []
	for segment in segments:
		parts = segment.split("\\n", 1)
		sectionTitle = parts[0].strip()
		if not sectionTitle:
			continue
		sectionContent = parts[1].replace("\\n", " ").strip() if len(parts) > 1 else ""
		result.append((sectionTitle, sectionContent))
	return result


def _getBlueprintInfo(element: etree._Element) -> list[tuple[str, str]]:  # type: ignore[name-defined]
	"""Return Blueprint-related (sectionTitle, sectionContent) pairs from element.

	Searches the element's ``<detaileddescription>`` for ``<simplesect kind="par">``
	entries whose parsed title starts with ``"Blueprint"``.  Works for both
	``memberdef`` and ``compounddef`` elements.
	"""
	result: list[tuple[str, str]] = []
	detailedDescription = element.find("detaileddescription")
	if detailedDescription is None:
		return result
	for simplesect in detailedDescription.iter("simplesect"):
		if simplesect.get("kind") != "par":
			continue
		titleElement = simplesect.find("title")
		if titleElement is None:
			continue
		titleText = (titleElement.text or "").strip()
		for sectionTitle, sectionContent in _parseParTitleSegments(titleText):
			if sectionTitle.startswith("Blueprint"):
				result.append((sectionTitle, sectionContent))
	return result


def _isBlueprintAccessible(blueprintInfo: list[tuple[str, str]]) -> bool:
	"""Return True if blueprintInfo contains at least one positive Blueprint access specifier.

	Excludes entries that explicitly restrict Blueprint access, such as
	``"Not Blueprintable"``, ``"Not BlueprintType"``, and
	``"Native only — not accessible to non-native Blueprints"``.
	"""
	for _, sectionContent in blueprintInfo:
		if sectionContent.startswith("Not "):
			continue
		if "not accessible to non-native Blueprints" in sectionContent:
			continue
		return True
	return False


def _blueprintSection(blueprintInfo: list[tuple[str, str]]) -> str:
	"""Build the ``## Blueprint`` section markdown for a member or class page.

	Returns an empty string when blueprintInfo is empty.
	"""
	if not blueprintInfo:
		return ""
	lines: list[str] = ["## Blueprint", ""]
	for sectionTitle, sectionContent in blueprintInfo:
		if sectionContent:
			lines.append("**{}:** {}".format(sectionTitle, sectionContent))
		else:
			lines.append("**{}**".format(sectionTitle))
		lines.append("")
	return "\n".join(lines)


def _functionPage(memberElement: etree._Element, compoundName: str) -> str:  # type: ignore[name-defined]
	"""Build a Markdown page for a single (non-overloaded) member function."""
	functionName = _getText(memberElement.find("name"))
	returnType = _getText(memberElement.find("type"))
	# Collect return description and Blueprint info before _description() removes
	# <simplesect> elements from the detaileddescription tree.
	returnDescription = _getReturnDescription(memberElement)
	blueprintInfo = _getBlueprintInfo(memberElement)
	brief = _description(memberElement.find("briefdescription"))
	detail = _description(memberElement.find("detaileddescription"))
	parameterList = _collectParams(memberElement)
	syntax = _functionSyntax(memberElement)

	lines: list[str] = [
		"---",
		"title: {}".format(functionName),
		"---",
		"",
		"# {}::{}".format(compoundName.rsplit("::", 1)[-1], functionName),
		"",
		"**Class:** `{}`".format(compoundName),
		"",
	]
	if brief:
		lines += [brief, ""]

	lines += ["## Syntax", "", _codeBlock(syntax), ""]

	if parameterList:
		lines += ["## Parameters", "", _paramsTable(parameterList), ""]

	if returnType and returnType not in ("void", ""):
		lines += ["## Return Value", ""]
		if returnDescription:
			lines += [returnDescription, ""]
		else:
			lines += ["`{}`".format(returnType), ""]

	blueprintText = _blueprintSection(blueprintInfo)
	if blueprintText:
		lines += [blueprintText, ""]

	if detail:
		lines += ["## Remarks", "", detail, ""]

	return "\n".join(lines)


def _functionOverloadsPage(
	memberElements: list[etree._Element],  # type: ignore[name-defined]
	compoundName: str,
) -> str:
	"""Build a Markdown page for a function name, grouping all overloads.

	If only one overload exists the output is identical to ``_functionPage``.
	For multiple overloads each one is rendered as a ``### Overload N``
	subsection under a top-level ``## Overloads`` heading.
	"""
	if len(memberElements) == 1:
		return _functionPage(memberElements[0], compoundName)

	functionName = _getText(memberElements[0].find("name"))
	lines: list[str] = [
		"---",
		"title: {}".format(functionName),
		"---",
		"",
		"# {}::{}".format(compoundName.rsplit("::", 1)[-1], functionName),
		"",
		"**Class:** `{}`".format(compoundName),
		"",
		"## Overloads",
		"",
	]

	for i, memberElement in enumerate(memberElements, 1):
		returnType = _getText(memberElement.find("type"))
		syntax = _functionSyntax(memberElement)
		parameterList = _collectParams(memberElement)
		# Collect return description and Blueprint info before _description() removes
		# <simplesect> elements from the detaileddescription tree.
		returnDescription = _getReturnDescription(memberElement)
		blueprintInfo = _getBlueprintInfo(memberElement)
		brief = _description(memberElement.find("briefdescription"))
		detail = _description(memberElement.find("detaileddescription"))

		lines += ["### Overload {}".format(i), "", _codeBlock(syntax), ""]

		if brief:
			lines += [brief, ""]

		if parameterList:
			lines += ["**Parameters**", "", _paramsTable(parameterList), ""]

		if returnType and returnType not in ("void", ""):
			lines += ["**Return Value**", ""]
			if returnDescription:
				lines += [returnDescription, ""]
			else:
				lines += ["`{}`".format(returnType), ""]

		blueprintText = _blueprintSection(blueprintInfo)
		if blueprintText:
			lines += [blueprintText, ""]

		if detail:
			lines += ["**Remarks**", "", detail, ""]

	return "\n".join(lines)


def _propertyPage(memberElement: etree._Element, compoundName: str) -> str:  # type: ignore[name-defined]
	"""Build a Markdown page for a UPROPERTY member variable."""
	variableName = _getText(memberElement.find("name"))
	variableType = _getText(memberElement.find("type"))
	definition = _getText(memberElement.find("definition"))
	# Collect Blueprint info before _description() removes <simplesect> elements.
	blueprintInfo = _getBlueprintInfo(memberElement)
	brief = _description(memberElement.find("briefdescription"))
	detail = _description(memberElement.find("detaileddescription"))

	lines: list[str] = [
		"---",
		"title: {}".format(variableName),
		"---",
		"",
		"# {}::{}".format(compoundName.rsplit("::", 1)[-1], variableName),
		"",
		"**Class:** `{}`".format(compoundName),
		"",
	]
	if brief:
		lines += [brief, ""]

	syntax = definition if definition else "{} {}".format(variableType, variableName)
	lines += ["## Declaration", "", _codeBlock(syntax), ""]

	blueprintText = _blueprintSection(blueprintInfo)
	if blueprintText:
		lines += [blueprintText, ""]

	if detail:
		lines += ["## Remarks", "", detail, ""]

	return "\n".join(lines)


def _classDeclaration(compoundElement: etree._Element, className: str) -> str:  # type: ignore[name-defined]
	"""Build the C++ class/struct declaration line for the Syntax section."""
	kind = compoundElement.get("kind", "class")
	shortName = className.rsplit("::", 1)[-1]
	basesList: list[str] = []
	for baseElement in compoundElement.findall("basecompoundref"):
		protection = baseElement.get("prot", "public")
		baseName = (baseElement.text or "").strip()
		if baseName:
			basesList.append("{} {}".format(protection, baseName))
	baseString = " : " + ", ".join(basesList) if basesList else ""
	return "{} {}{}".format(kind, shortName, baseString)


def _classIndexPage(
	compoundElement: etree._Element,  # type: ignore[name-defined]
	className: str,
	compoundBrief: str,
	compoundDetail: str,
	functionBriefs: dict[str, str],
	functionSignatures: dict[str, list[str]],
	functionBlueprintAccessible: dict[str, bool],
	propertyBriefs: dict[str, str],
	propertyTypes: dict[str, str],
	propertyBlueprintAccessible: dict[str, bool],
	delegateBriefs: dict[str, str],
	delegateTypes: dict[str, str],
	delegateBlueprintAccessible: dict[str, bool],
) -> str:
	"""Build the index page for a class / struct."""
	lines: list[str] = ["# {}".format(className), ""]

	if compoundBrief:
		lines += [compoundBrief, ""]

	lines += ["## Syntax", "", _codeBlock(_classDeclaration(compoundElement, className)), ""]

	if compoundDetail:
		lines += ["## Remarks", "", compoundDetail, ""]

	classBlueprintText = _blueprintSection(_getBlueprintInfo(compoundElement))
	if classBlueprintText:
		lines += [classBlueprintText, ""]

	if functionBriefs:
		rows = [
			"| Method | Signature | Description | Blueprint |",
			"|--------|-----------|-------------|-----------|",
		]
		for name in sorted(functionBriefs):
			signatureCell = "<br>".join("`{}`".format(sig) for sig in functionSignatures.get(name, []))
			blueprintCell = "yes" if functionBlueprintAccessible.get(name) else ""
			rows.append("| [{}]({}.md) | {} | {} | {} |".format(name, name, signatureCell, functionBriefs[name], blueprintCell))
		lines += ["## Methods", "", "\n".join(rows), ""]

	if propertyBriefs:
		rows = [
			"| Property | Type | Description | Blueprint |",
			"|----------|------|-------------|-----------|",
		]
		for name in sorted(propertyBriefs):
			blueprintCell = "yes" if propertyBlueprintAccessible.get(name) else ""
			rows.append("| [{}]({}.md) | `{}` | {} | {} |".format(name, name, propertyTypes.get(name, ""), propertyBriefs[name], blueprintCell))
		lines += ["## Properties", "", "\n".join(rows), ""]

	if delegateBriefs:
		rows = [
			"| Delegate | Type | Description | Blueprint |",
			"|----------|------|-------------|-----------|",
		]
		for name in sorted(delegateBriefs):
			blueprintCell = "yes" if delegateBlueprintAccessible.get(name) else ""
			rows.append("| [{}]({}.md) | `{}` | {} | {} |".format(name, name, delegateTypes.get(name, ""), delegateBriefs[name], blueprintCell))
		lines += ["## Delegates", "", "\n".join(rows), ""]

	return "\n".join(lines)


# ---------------------------------------------------------------------------
# Compound processor
# ---------------------------------------------------------------------------

_MEMBER_KINDS_FUNCTION = {"function"}
_MEMBER_KINDS_VARIABLE = {"variable"}


def _isDelegateType(variableType: str) -> bool:
	"""Return True if variableType looks like a UE delegate type.

	Matches the two dominant UE naming conventions: types that contain the
	word ``Delegate`` (e.g. ``FSetDisplayTextDelegate``) and types that begin
	with ``FOn`` (e.g. ``FOnEnumerateStreamsComplete``).
	"""
	return "Delegate" in variableType or variableType.startswith("FOn")


def _extractPluginName(compoundElement: etree._Element) -> str | None:  # type: ignore[name-defined]
	"""Extract the plugin name from the compound's ``<location>`` element.

	Looks for a ``Source`` directory in the file path and returns the path
	component immediately before it.  This works for both standard Unreal
	layouts (``Plugins/<Plugin>/Source/...``) and custom ones such as
	``<RootDir>/<Plugin>/Source/...``.  Returns ``None`` when no ``Source``
	segment is found or when ``Source`` is the first path component.
	"""
	locationElement = compoundElement.find("location")
	if locationElement is None:
		return None
	filePath = locationElement.get("file", "").replace("\\", "/")
	pathComponents = filePath.split("/")
	try:
		sourceIndex = pathComponents.index("Source")
	except ValueError:
		return None
	if sourceIndex == 0:
		return None
	return pathComponents[sourceIndex - 1]


def processCompound(
	xmlPath: Path, outputDirectory: Path
) -> tuple[str, str, str, str, str | None] | None:
	"""Process one Doxygen compound XML file.

	Returns ``(compoundName, compoundBrief, compoundDetail, compoundKind,
	pluginName)`` on success, or ``None`` for compound kinds that are skipped
	(e.g. namespaces, raw files).  ``pluginName`` is ``None`` when the
	compound does not belong to a plugin.
	"""
	tree = etree.parse(str(xmlPath))
	root = tree.getroot()

	compoundElement = root.find("compounddef")
	if compoundElement is None:
		return None

	kind = compoundElement.get("kind", "")
	if kind not in ("class", "struct", "enum", "namespace"):
		return None

	compoundName = _getText(compoundElement.find("compoundname"))
	if kind == "namespace" and (compoundName == "std" or compoundName.startswith("std::")):
		return None
	# Use the last component for the directory name (strip namespace prefix).
	shortName = compoundName.rsplit("::", 1)[-1]
	pluginName = _extractPluginName(compoundElement)

	if pluginName:
		classDirectory = outputDirectory / pluginName / shortName
	else:
		classDirectory = outputDirectory / shortName
	classDirectory.mkdir(parents=True, exist_ok=True)

	# Group function members by name to merge overloads onto one page.
	# Insertion order is preserved so the page order matches the header file.
	functionGroups: dict[str, list[etree._Element]] = {}  # type: ignore[name-defined]
	functionBriefs: dict[str, str] = {}
	functionSignatures: dict[str, list[str]] = {}
	functionBlueprintAccessible: dict[str, bool] = {}
	propertyBriefs: dict[str, str] = {}
	propertyTypes: dict[str, str] = {}
	propertyBlueprintAccessible: dict[str, bool] = {}
	delegateBriefs: dict[str, str] = {}
	delegateTypes: dict[str, str] = {}
	delegateBlueprintAccessible: dict[str, bool] = {}

	for memberElement in compoundElement.iter("memberdef"):
		memberKind = memberElement.get("kind", "")
		memberProtection = memberElement.get("prot", "public")
		if memberProtection not in ("public", "protected"):
			continue

		name = _getText(memberElement.find("name"))
		if not name:
			continue

		if memberKind in _MEMBER_KINDS_FUNCTION:
			functionGroups.setdefault(name, []).append(memberElement)
			# Record the brief of the first overload for the class index table.
			if name not in functionBriefs:
				functionBriefs[name] = _description(memberElement.find("briefdescription"))
			functionSignatures.setdefault(name, []).append(_functionSyntax(memberElement))
			# A function is blueprint accessible if any overload is accessible.
			if _isBlueprintAccessible(_getBlueprintInfo(memberElement)):
				functionBlueprintAccessible[name] = True
			elif name not in functionBlueprintAccessible:
				functionBlueprintAccessible[name] = False
		elif memberKind in _MEMBER_KINDS_VARIABLE:
			brief = _description(memberElement.find("briefdescription"))
			variableType = _getText(memberElement.find("type"))
			isAccessible = _isBlueprintAccessible(_getBlueprintInfo(memberElement))
			page = _propertyPage(memberElement, compoundName)
			(classDirectory / "{}.md".format(name)).write_text(page, encoding="utf-8")
			if _isDelegateType(variableType):
				delegateBriefs[name] = brief
				delegateTypes[name] = variableType
				delegateBlueprintAccessible[name] = isAccessible
			else:
				propertyBriefs[name] = brief
				propertyTypes[name] = variableType
				propertyBlueprintAccessible[name] = isAccessible

	for functionName, overloads in functionGroups.items():
		page = _functionOverloadsPage(overloads, compoundName)
		(classDirectory / "{}.md".format(functionName)).write_text(page, encoding="utf-8")

	# Capture both descriptions before _classIndexPage would otherwise consume them.
	compoundBrief = _description(compoundElement.find("briefdescription"))
	compoundDetail = _description(compoundElement.find("detaileddescription"))

	indexPage = _classIndexPage(
		compoundElement, compoundName,
		compoundBrief, compoundDetail,
		functionBriefs, functionSignatures, functionBlueprintAccessible,
		propertyBriefs, propertyTypes, propertyBlueprintAccessible,
		delegateBriefs, delegateTypes, delegateBlueprintAccessible,
	)
	(classDirectory / "index.md").write_text(indexPage, encoding="utf-8")

	return compoundName, compoundBrief, compoundDetail, kind, pluginName


# ---------------------------------------------------------------------------
# Plugin and top-level indexes
# ---------------------------------------------------------------------------

def _writePluginIndex(
	pluginDirectory: Path,
	pluginName: str,
	compoundEntries: list[tuple[str, str, str, str]],
	pluginDescription: tuple[str, str],
) -> None:
	"""Write an MSDN-style index page listing all compounds in a plugin."""
	pluginBrief, pluginDetail = pluginDescription
	lines: list[str] = ["# {} plugin".format(pluginName), ""]
	if pluginBrief:
		lines += [pluginBrief, ""]
	if pluginDetail:
		lines += [pluginDetail, ""]

	sectionConfig = [
		("class",  "## Classes"),
		("struct", "## Structs"),
		("enum",   "## Enums"),
	]
	for kindFilter, sectionHeader in sectionConfig:
		filtered = sorted(
			[(name, brief) for name, brief, _, kind in compoundEntries if kind == kindFilter],
			key = lambda entry: entry[0],
		)
		if not filtered:
			continue
		tableRows = [
			"| {} | Description |".format(kindFilter.capitalize()),
			"|-------|-------------|",
		]
		for name, brief in filtered:
			shortName = name.rsplit("::", 1)[-1]
			tableRows.append("| [{}]({}/index.md) | {} |".format(name, shortName, brief))
		lines += [sectionHeader, "", "\n".join(tableRows), ""]

	(pluginDirectory / "index.md").write_text("\n".join(lines), encoding="utf-8")


def _writeTopIndex(
	outputDirectory: Path,
	pluginMap: dict[str | None, list[tuple[str, str, str, str]]],
	pluginDescriptions: dict[str, tuple[str, str]],
) -> None:
	"""Write the root index page, organised by plugin then by loose class."""
	lines: list[str] = [
		"# API Reference",
		"",
		"Generated by [Unreal-Doxygen](https://github.com/candytaco/Unreal-Doxygen).",
		"",
	]

	for pluginName in sorted(name for name in pluginMap if name is not None):
		lines.append("## [{} plugin]({}/index.md)".format(pluginName, pluginName))
		lines.append("")
		pluginBrief, _ = pluginDescriptions.get(pluginName, ("", ""))
		if pluginBrief:
			lines += [pluginBrief, ""]

	nonPluginEntries = pluginMap.get(None, [])
	if nonPluginEntries:
		lines += ["## Classes", ""]
		for name in sorted(entry[0] for entry in nonPluginEntries):  # entry is (name, brief, detail, kind)
			shortName = name.rsplit("::", 1)[-1]
			lines.append("- [{}]({}/index.md)".format(name, shortName))
		lines.append("")

	(outputDirectory / "index.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def convert(xmlDirectory: Path, outputDirectory: Path) -> None:
	"""Convert all compound XML files in xmlDirectory to Markdown in outputDirectory."""
	outputDirectory.mkdir(parents=True, exist_ok=True)

	# Maps plugin name (or None for non-plugin compounds) to (name, brief, detail, kind) tuples.
	pluginMap: dict[str | None, list[tuple[str, str, str, str]]] = {}
	pluginDescriptions: dict[str, tuple[str, str]] = {}

	xmlFiles = list(xmlDirectory.glob("*.xml"))
	if not xmlFiles:
		print(
			"warning: no XML files found in {}".format(xmlDirectory),
			file=sys.stderr,
		)
		return

	for xmlFile in sorted(xmlFiles):
		if xmlFile.name in ("index.xml", "Doxyfile.xml"):
			continue
		result = processCompound(xmlFile, outputDirectory)
		if result is not None:
			compoundName, compoundBrief, compoundDetail, compoundKind, pluginName = result
			pluginMap.setdefault(pluginName, []).append((compoundName, compoundBrief, compoundDetail, compoundKind))
			print("  converted: {} → {}".format(xmlFile.name, compoundName))

	# Derive plugin descriptions from the FXxxModule compound brief and detail.
	# Unreal Engine module classes follow the IModuleInterface convention and
	# their names end with "Module" (e.g. FEyelinkModule, FMRIExperimentModule).
	for pluginName, entries in pluginMap.items():
		if pluginName is None:
			continue
		for compoundName, compoundBrief, compoundDetail, compoundKind in entries:
			shortName = compoundName.rsplit("::", 1)[-1]
			if compoundKind == "class" and shortName.endswith("Module") and compoundBrief:
				pluginDescriptions[pluginName] = (compoundBrief, compoundDetail)
				break

	for pluginName, compoundEntries in pluginMap.items():
		if pluginName is not None:
			_writePluginIndex(
				outputDirectory / pluginName, pluginName, compoundEntries,
				pluginDescriptions.get(pluginName, ("", "")),
			)

	_writeTopIndex(outputDirectory, pluginMap, pluginDescriptions)

	totalCount = sum(len(names) for names in pluginMap.values())
	print("\nWrote {} compound(s) to {}/".format(totalCount, outputDirectory))


def main(argv: list[str] | None = None) -> None:
	parser = argparse.ArgumentParser(
		description = "Convert Doxygen XML output to per-page Markdown."
	)
	parser.add_argument(
		"--xml-dir",
		metavar = "DIR",
		default = "docs/xml",
		help = "Directory containing Doxygen XML output (default: docs/xml)",
	)
	parser.add_argument(
		"--output-dir",
		metavar = "DIR",
		default = "docs/md",
		help = "Directory to write Markdown files to (default: docs/md)",
	)
	args = parser.parse_args(argv)

	xmlDirectory = Path(args.xml_dir)
	outputDirectory = Path(args.output_dir)

	if not xmlDirectory.exists():
		print("error: XML directory not found: {}".format(xmlDirectory), file=sys.stderr)
		sys.exit(1)

	convert(xmlDirectory, outputDirectory)


if __name__ == "__main__":
	main()
