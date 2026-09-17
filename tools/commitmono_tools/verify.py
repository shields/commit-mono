"""Compare rebuilt binaries against the shipped originals.

A rebuild is considered faithful when every glyph has the same outline structure and
its points lie within a tolerance (rounding of the fractional coordinates in the italic
CFF sources), advances are identical, and the layout and metadata tables match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.ttGlyphSet import _TTGlyphSet
from fontTools.varLib import instancer

DEFAULT_TOLERANCE = 1.0
# docs/building.md documents left side bearing drift up to 1 unit for italic statics
# (rounded fractional xMin) and up to 6 units for the variable font's phantom-point
# quirk; anything past that is a real regression, not the known rounding noise. The two
# are checked separately: applying the variable font's 6-unit ceiling to statics too
# would let a 2-to-6-unit static regression through as a note instead of a problem.
MAX_EXPECTED_STATIC_LSB_DEVIATION = 1
MAX_EXPECTED_VARIABLE_LSB_DEVIATION = 6
DEFAULT_LOCATIONS: tuple[dict[str, float], ...] = (
    {"wght": 200, "ital": 0},
    {"wght": 400, "ital": 0},
    {"wght": 700, "ital": 0},
    {"wght": 200, "ital": 1},
    {"wght": 400, "ital": 1},
    {"wght": 700, "ital": 1},
    {"wght": 550, "ital": 0.5},
    {"wght": 300, "ital": 0.505},
    {"wght": 200, "ital": 0.51},
    {"wght": 700, "ital": 0.51},
)
_NAME_IDS = (1, 2, 4, 6, 16, 17)
_METRIC_FIELDS = {
    "hhea": ("ascent", "descent", "lineGap", "caretSlopeRise", "caretSlopeRun"),
    "OS/2": (
        "usWeightClass",
        "usWidthClass",
        "fsType",
        "fsSelection",
        "sTypoAscender",
        "sTypoDescender",
        "sTypoLineGap",
        "usWinAscent",
        "usWinDescent",
        "xAvgCharWidth",
        "sxHeight",
        "sCapHeight",
    ),
    "head": ("unitsPerEm", "macStyle", "xMin", "yMin", "xMax", "yMax"),
    "post": ("italicAngle", "isFixedPitch", "underlinePosition", "underlineThickness"),
}


@dataclass
class Report:
    name: str
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def render(self) -> str:
        status = "OK" if self.ok else "FAIL"
        lines = [f"{status}  {self.name}"]
        lines += [f"    problem: {p}" for p in self.problems]
        lines += [f"    note: {n}" for n in self.notes]
        return "\n".join(lines)


def _outline(glyph_set: _TTGlyphSet, name: str) -> tuple[list[tuple[str, int]], list[float]]:
    pen = DecomposingRecordingPen(glyph_set)
    glyph_set[name].draw(pen)
    structure = [(operator, len(operands)) for operator, operands in pen.value]
    coordinates = [c for _, operands in pen.value for point in operands for c in point]
    return structure, coordinates


def _compare_glyphs(
    original: TTFont, built: TTFont, tolerance: float, report: Report, label: str, max_lsb_deviation: float
) -> None:
    order = original.getGlyphOrder()
    if order != built.getGlyphOrder():
        report.problems.append(f"{label}: glyph order differs")
        return
    original_set, built_set = original.getGlyphSet(), built.getGlyphSet()
    structural: list[str] = []
    moved: list[tuple[float, str]] = []
    worst = 0.0
    advances: list[str] = []
    bearings: list[tuple[int, str]] = []
    for name in order:
        structure_a, coords_a = _outline(original_set, name)
        structure_b, coords_b = _outline(built_set, name)
        if structure_a != structure_b:
            structural.append(name)
        else:
            delta = max((abs(a - b) for a, b in zip(coords_a, coords_b, strict=True)), default=0.0)
            worst = max(worst, delta)
            if delta > tolerance:
                moved.append((delta, name))
        advance_a, lsb_a = original["hmtx"][name]
        advance_b, lsb_b = built["hmtx"][name]
        if advance_a != advance_b:
            advances.append(name)
        if lsb_a != lsb_b:
            bearings.append((abs(lsb_a - lsb_b), name))
    if structural:
        report.problems.append(f"{label}: {len(structural)} glyphs changed outline structure, e.g. {structural[:5]}")
    if moved:
        moved.sort(reverse=True)
        report.problems.append(
            f"{label}: {len(moved)} glyphs moved more than {tolerance:g} units, "
            f"worst {moved[0][1]} by {moved[0][0]:.2f}"
        )
    if advances:
        report.problems.append(f"{label}: {len(advances)} glyphs changed advance width, e.g. {advances[:5]}")
    report.notes.append(f"{label}: max outline deviation {worst:.2f} units")
    if bearings:
        bearings.sort(reverse=True)
        message = (
            f"{label}: {len(bearings)} glyphs differ in left side bearing (max {bearings[0][0]}, e.g. {bearings[0][1]})"
        )
        if bearings[0][0] > max_lsb_deviation:
            report.problems.append(message)
        else:
            report.notes.append(message)


def _feature_tags(font: TTFont, table: str) -> list[str]:
    if table not in font:
        return []
    return sorted({record.FeatureTag for record in font[table].table.FeatureList.FeatureRecord})


def _gdef_classes(font: TTFont) -> dict[str, int] | None:
    if "GDEF" not in font or font["GDEF"].table.GlyphClassDef is None:
        return None
    return dict(font["GDEF"].table.GlyphClassDef.classDefs)


def _cmap_subtables(font: TTFont) -> dict[tuple[int, int], dict[int, str]]:
    """Every cmap subtable keyed by (platform, encoding), not just the one ``getBestCmap``
    picks for Unicode lookup."""
    return {(t.platformID, t.platEncID): dict(t.cmap) for t in font["cmap"].tables}


def _compare_cmap(original: TTFont, built: TTFont, report: Report) -> None:
    cmap_a, cmap_b = _cmap_subtables(original), _cmap_subtables(built)
    # fontmake doesn't emit legacy Mac subtables; treat a dropped subtable like a dropped
    # table (a note, same as DSIG/GPOS below) but a changed or added one as a real problem.
    dropped = sorted(set(cmap_a) - set(cmap_b))
    added = sorted(set(cmap_b) - set(cmap_a))
    changed = sorted(key for key in cmap_a.keys() & cmap_b.keys() if cmap_a[key] != cmap_b[key])
    if dropped:
        report.notes.append(f"cmap subtables not in rebuild: {dropped}")
    if added:
        report.problems.append(f"cmap subtables added by rebuild: {added}")
    if changed:
        report.problems.append(f"cmap subtables differ: {changed}")


def _compare_tables(original: TTFont, built: TTFont, report: Report) -> None:
    _compare_cmap(original, built, report)
    for table in ("GSUB", "GPOS"):
        tags_a, tags_b = _feature_tags(original, table), _feature_tags(built, table)
        if tags_a != tags_b:
            report.problems.append(f"{table} feature tags differ: {tags_a} vs {tags_b}")
        if table in original and table in built:
            count_a = original[table].table.LookupList.LookupCount
            count_b = built[table].table.LookupList.LookupCount
            if count_a != count_b:
                report.problems.append(f"{table} lookup count differs: {count_a} vs {count_b}")
    if _gdef_classes(original) != _gdef_classes(built):
        report.problems.append("GDEF glyph classes differ")
    for table, fields in _METRIC_FIELDS.items():
        for attribute in fields:
            value_a, value_b = getattr(original[table], attribute), getattr(built[table], attribute)
            if value_a != value_b:
                report.problems.append(f"{table}.{attribute} differs: {value_a} vs {value_b}")
    for name_id in _NAME_IDS:
        value_a = original["name"].getDebugName(name_id)
        value_b = built["name"].getDebugName(name_id)
        if value_a != value_b:
            (report.notes if value_a is None else report.problems).append(
                f"name {name_id} differs: {value_a!r} vs {value_b!r}"
            )
    dropped = sorted(set(original.keys()) - set(built.keys()) - {"GlyphOrder"})
    if dropped:
        report.notes.append(f"tables not in rebuild: {dropped}")
    added = sorted(set(built.keys()) - set(original.keys()) - {"GlyphOrder"})
    if added:
        report.problems.append(f"tables added by rebuild: {added}")


def verify_static(original_path: Path, built_path: Path, tolerance: float = DEFAULT_TOLERANCE) -> Report:
    report = Report(built_path.name)
    original, built = TTFont(original_path), TTFont(built_path)
    _compare_tables(original, built, report)
    _compare_glyphs(original, built, tolerance, report, "outlines", MAX_EXPECTED_STATIC_LSB_DEVIATION)
    return report


def _named_instances(font: TTFont) -> list[tuple[dict[str, float], str | None]]:
    name = font["name"]
    return [(dict(i.coordinates), name.getDebugName(i.subfamilyNameID)) for i in font["fvar"].instances]


def verify_variable(
    original_path: Path,
    built_path: Path,
    tolerance: float = DEFAULT_TOLERANCE,
    locations: tuple[dict[str, float], ...] = DEFAULT_LOCATIONS,
) -> Report:
    report = Report(built_path.name)
    original, built = TTFont(original_path), TTFont(built_path)
    _compare_tables(original, built, report)
    if _named_instances(original) != _named_instances(built):
        report.problems.append("fvar named instances differ")
    for table in ("STAT", "MVAR", "HVAR", "gvar"):
        if (table in original) != (table in built):
            report.problems.append(f"{table} presence differs")
    if "MVAR" in original and "MVAR" in built:
        tags_a = sorted(r.ValueTag for r in original["MVAR"].table.ValueRecord)
        tags_b = sorted(r.ValueTag for r in built["MVAR"].table.ValueRecord)
        if tags_a != tags_b:
            report.problems.append(f"MVAR tags differ: {tags_a} vs {tags_b}")
    for location in locations:
        label = "at " + " ".join(f"{tag}={value:g}" for tag, value in location.items())
        instance_a = instancer.instantiateVariableFont(original, location, inplace=False)
        instance_b = instancer.instantiateVariableFont(built, location, inplace=False)
        _compare_glyphs(instance_a, instance_b, tolerance, report, label, MAX_EXPECTED_VARIABLE_LSB_DEVIATION)
    return report
