"""Describe the OpenType layout of a binary: features, lookups and substitution rules.

Also reads the customization catalog in ``src/js/website_data.js`` so the generated
reference carries the same labels and descriptions as the website.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables.otBase import BaseTable

_LOOKUP_TYPES = {
    1: "single substitution",
    2: "multiple substitution",
    3: "alternate substitution",
    4: "ligature substitution",
    5: "contextual substitution",
    6: "chained contextual substitution",
    8: "reverse chained substitution",
}


@dataclass
class Lookup:
    index: int
    kind: str
    rules: list[str] = field(default_factory=list)
    rule_count: int = 0
    nested: bool = False
    calls: set[int] = field(default_factory=set)


@dataclass
class Feature:
    tag: str
    lookups: list[Lookup]
    classes: list[str] = field(default_factory=list)


class _Classes:
    """Names glyph sets that contextual rules reuse, so each set is spelled out once."""

    def __init__(self) -> None:
        self._names: dict[tuple[str, ...], str] = {}

    def name(self, glyphs: list[str]) -> str:
        if len(glyphs) == 1:
            return glyphs[0]
        key = tuple(glyphs)
        if key not in self._names:
            self._names[key] = f"@class{len(self._names) + 1}"
        return self._names[key]

    def definitions(self, shown: int = 8) -> list[str]:
        lines = []
        for glyphs, name in self._names.items():
            more = f" … +{len(glyphs) - shown}" if len(glyphs) > shown else ""
            lines.append(f"{name} = [{' '.join(glyphs[:shown])}{more}] ({len(glyphs)} glyphs)")
        return lines


@dataclass
class CatalogEntry:
    tag: str
    kind: str
    label: str
    description: str
    example: str
    default_on: bool


def _glyphs(coverage: BaseTable | None) -> list[str]:
    return list(coverage.glyphs) if coverage is not None else []


def _describe_subtable(subtable: BaseTable, lookup: Lookup, classes: _Classes) -> None:
    kind = subtable.LookupType
    if kind == 7:
        _describe_subtable(subtable.ExtSubTable, lookup, classes)
        return
    if kind == 1:
        rules = [f"{a} → {b}" for a, b in subtable.mapping.items()]
    elif kind == 2:
        rules = [f"{a} → {' '.join(b)}" for a, b in subtable.mapping.items()]
    elif kind == 3:
        rules = [f"{a} → [{' '.join(b)}]" for a, b in subtable.alternates.items()]
    elif kind == 4:
        rules = [
            f"{first} {' '.join(lig.Component)} → {lig.LigGlyph}"
            for first, ligatures in subtable.ligatures.items()
            for lig in ligatures
        ]
    elif kind in (5, 6):
        rules = _describe_contextual(subtable, lookup, classes)
    else:
        rules = [f"(lookup type {kind} not described)"]
    lookup.rules.extend(rules)
    lookup.rule_count += len(rules)


def _rules_of(rule_set: object, chain_attr: str, plain_attr: str) -> list[object]:
    return getattr(rule_set, chain_attr) if hasattr(rule_set, chain_attr) else getattr(rule_set, plain_attr)


def _describe_contextual(subtable: BaseTable, lookup: Lookup, classes: _Classes) -> list[str]:
    fmt = subtable.Format
    if fmt == 3:
        # Stored in reverse (nearest-to-input-first) order per the OpenType spec; reverse
        # it back so the rendered sequence reads left to right like the input/lookahead do.
        backtrack = [_glyphs(c) for c in reversed(getattr(subtable, "BacktrackCoverage", []))]
        inputs = [_glyphs(c) for c in getattr(subtable, "InputCoverage", getattr(subtable, "Coverage", []))]
        lookahead = [_glyphs(c) for c in getattr(subtable, "LookAheadCoverage", [])]
        records = getattr(subtable, "SubstLookupRecord", [])
        lookup.calls.update(r.LookupListIndex for r in records)
        actions = ", ".join(f"lookup {r.LookupListIndex} at input {r.SequenceIndex}" for r in records)
        if not actions:
            actions = "no substitution (blocks later rules)"
        sets = [_sets(group, classes) for group in (backtrack, inputs, lookahead)]
        return [f"{sets[0]} | {sets[1]} | {sets[2]} → {actions}"]
    if fmt == 2:
        rule_sets = getattr(subtable, "ChainSubClassSet", getattr(subtable, "SubClassSet", []))
        rules = [rule for rs in rule_sets if rs for rule in _rules_of(rs, "ChainSubClassRule", "SubClassRule")]
        for rule in rules:
            lookup.calls.update(r.LookupListIndex for r in getattr(rule, "SubstLookupRecord", []))
        return [f"{len(rules)} class-based rules over {len(_glyphs(subtable.Coverage))} first glyphs"]
    rule_sets = getattr(subtable, "ChainSubRuleSet", getattr(subtable, "SubRuleSet", []))
    rules = [rule for rs in rule_sets if rs for rule in _rules_of(rs, "ChainSubRule", "SubRule")]
    for rule in rules:
        lookup.calls.update(r.LookupListIndex for r in getattr(rule, "SubstLookupRecord", []))
    return [f"{len(rules)} glyph-based rules over {len(_glyphs(subtable.Coverage))} first glyphs"]


def _sets(groups: list[list[str]], classes: _Classes) -> str:
    return " ".join(classes.name(group) for group in groups) if groups else "-"


def _describe_lookup(table: BaseTable, index: int, classes: _Classes, nested: bool) -> Lookup:
    raw = table.LookupList.Lookup[index]
    kind = raw.LookupType
    if kind == 7:
        kind = raw.SubTable[0].ExtSubTable.LookupType
    lookup = Lookup(index, _LOOKUP_TYPES.get(kind, f"type {kind}"), nested=nested)
    for subtable in raw.SubTable:
        _describe_subtable(subtable, lookup, classes)
    return lookup


def gsub_features(font: TTFont) -> list[Feature]:
    """Every GSUB feature tag with its lookups, the lookups those call, and readable rules."""
    if "GSUB" not in font:
        return []
    table = font["GSUB"].table
    by_tag: dict[str, list[int]] = {}
    for record in table.FeatureList.FeatureRecord:
        indices = by_tag.setdefault(record.FeatureTag, [])
        for index in record.Feature.LookupListIndex:
            if index not in indices:
                indices.append(index)
    features = []
    for tag, indices in sorted(by_tag.items()):
        classes = _Classes()
        lookups = [_describe_lookup(table, index, classes, nested=False) for index in indices]
        seen = set(indices)
        queue = [index for lookup in lookups for index in sorted(lookup.calls)]
        while queue:
            index = queue.pop(0)
            if index in seen:
                continue
            seen.add(index)
            nested = _describe_lookup(table, index, classes, nested=True)
            lookups.append(nested)
            queue.extend(sorted(nested.calls))
        features.append(Feature(tag, lookups, classes.definitions()))
    return features


def glyph_suffixes(font: TTFont) -> Counter[str]:
    """How many glyphs carry each name suffix (``.cv01``, ``.case``, ``.leftL`` ...).

    Suffixes stack (``colon.case.square``), so a glyph counts once for every suffix it
    carries, not just once for the whole dotted tail after its base name.
    """
    counts: Counter[str] = Counter()
    for name in font.getGlyphOrder():
        base, dot, rest = name.partition(".")
        if dot and base:
            for suffix in rest.split("."):
                counts["." + suffix] += 1
    return counts


_ENTRY_RE = re.compile(r"\{\s*type:\s*\"(alternate|feature)\",(.*?)\n\s*\},", re.DOTALL)
_FIELD_RE = re.compile(r"(\w+):\s*(\"(?:[^\"\\]|\\.)*\"|true|false)")


def website_catalog(js_path: Path) -> dict[str, CatalogEntry]:
    """Feature labels, descriptions and examples from the website's customization catalog."""
    entries: dict[str, CatalogEntry] = {}
    for match in _ENTRY_RE.finditer(js_path.read_text(encoding="utf-8")):
        fields: dict[str, str] = {"type": match.group(1)}
        for key, value in _FIELD_RE.findall(match.group(2)):
            fields[key] = value[1:-1] if value.startswith('"') else value
        if "feature" not in fields:
            continue
        entries[fields["feature"]] = CatalogEntry(
            tag=fields["feature"],
            kind=fields["type"],
            label=fields.get("label", ""),
            description=fields.get("description", ""),
            example=fields.get("docsExample", ""),
            default_on=fields.get("on") == "true",
        )
    if not entries:
        # _ENTRY_RE/_FIELD_RE are tied to website_data.js's current formatting (in
        # particular, a trailing comma after each entry's closing brace); fail loudly
        # rather than silently generating a reference with no feature descriptions.
        raise RuntimeError(f"no feature catalog entries found in {js_path}; _ENTRY_RE/_FIELD_RE may need updating")
    return entries


def render_markdown(font_path: Path, catalog: dict[str, CatalogEntry], rule_limit: int = 40) -> str:
    """Markdown reference for the layout features of one binary."""
    font = TTFont(font_path)
    lines = [
        "# OpenType feature reference",
        "",
        f"Generated by `cmfont features --write` from `{font_path.name}`. Do not edit by hand.",
        "",
        "Feature tags that the website exposes carry its label, description and example. "
        "`|DEF|`/`|ALT|` and `|OFF|`/`|ON|` in a description mark the two states.",
        "",
    ]
    for feature in gsub_features(font):
        entry = catalog.get(feature.tag)
        title = f"## {feature.tag}" + (f" — {entry.label}" if entry else "")
        lines += [title, ""]
        if entry:
            default = "on" if entry.default_on else "off"
            lines += [f"{entry.description}", "", f"Example: `{entry.example}` (default {default})", ""]
        if feature.classes:
            lines += ["Glyph classes used by the rules below:", ""]
            lines += [f"- `{definition}`" for definition in feature.classes]
            lines.append("")
        for lookup in feature.lookups:
            role = "Nested lookup" if lookup.nested else "Lookup"
            lines.append(f"- {role} {lookup.index}, {lookup.kind}, {lookup.rule_count} rules")
            shown = lookup.rules[:rule_limit]
            lines += [f"    - `{rule}`" for rule in shown]
            if len(lookup.rules) > rule_limit:
                lines.append(f"    - … {len(lookup.rules) - rule_limit} more")
        lines.append("")
    lines += ["## Glyph name suffixes", "", "| Suffix | Glyphs |", "|---|---|"]
    lines += [f"| `{suffix}` | {count} |" for suffix, count in glyph_suffixes(font).most_common()]
    lines.append("")
    return "\n".join(lines)
