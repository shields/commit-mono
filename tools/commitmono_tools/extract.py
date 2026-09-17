"""Turn the shipped binaries into editable UFO sources.

The repository has no font sources: the statics and the variable font were exported from
FontLab. ``extract_static`` decompiles one CFF OTF into a cubic UFO. ``extract_variable``
pulls point-compatible TrueType masters out of the variable font and writes a designspace
for them. Both apply fixups so that a fontmake rebuild reproduces the original tables.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import defcon
import extractor
from fontTools.designspaceLib import (
    AxisDescriptor,
    AxisLabelDescriptor,
    DesignSpaceDocument,
    InstanceDescriptor,
    SourceDescriptor,
)
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._n_a_m_e import table__n_a_m_e
from fontTools.varLib import instancer

# extractor writes this placeholder, and an explicit GDEF block stops ufo2ft from
# generating the real one from public.openTypeCategories.
_EMPTY_GDEF_RE = re.compile(r"table GDEF \{\s*GlyphClassDef \[\], \[\], \[\], \[\];\s*\} GDEF;\s*")
_GDEF_CATEGORIES = {1: "base", 2: "ligature", 3: "mark", 4: "component"}
# The UFO spec stores only these fsSelection bits; the others are derived at compile time.
_UFO_SELECTION_BITS = (1, 2, 3, 4, 7, 8, 9)


def _fix_ufo(ufo: defcon.Font, font: TTFont) -> None:
    """Restore what extractor drops or mangles, so a fontmake rebuild matches the original."""
    if ufo.features.text:
        text, replaced = _EMPTY_GDEF_RE.subn("", ufo.features.text)
        if "GDEF" in ufo.features.text and not replaced:
            # extractor is documented to always emit this exact placeholder; if a future
            # version formats it differently, fail loudly instead of shipping wrong GDEF.
            raise RuntimeError("extractor's GDEF block no longer matches _EMPTY_GDEF_RE; update the regex")
        ufo.features.text = text
    class_defs = font["GDEF"].table.GlyphClassDef if "GDEF" in font else None
    if class_defs is not None:
        categories = {}
        for name, cls in class_defs.classDefs.items():
            if name not in ufo:
                continue
            if cls not in _GDEF_CATEGORIES:
                # Deliberately an error rather than a skip: a class outside 1-4 is
                # malformed GDEF, and dropping it would silently change the rebuilt font.
                raise ValueError(f"GDEF assigns {name!r} the unknown glyph class {cls}")
            categories[name] = _GDEF_CATEGORIES[cls]
        ufo.lib["public.openTypeCategories"] = categories
    selection = font["OS/2"].fsSelection
    ufo.info.openTypeOS2Selection = [bit for bit in _UFO_SELECTION_BITS if selection & (1 << bit)]
    for glyph in ufo:
        # extractor stores TrueType instruction hashes that never match a rebuilt glyph.
        glyph.lib.pop("public.truetype.instructions", None)


def _extract(font_path: Path, dest: Path, keep_glyphs: frozenset[str] | None = None) -> defcon.Font:
    ufo = defcon.Font()
    extractor.extractUFO(str(font_path), ufo)
    if keep_glyphs is not None:
        # Prune before _fix_ufo, which stamps public.openTypeCategories for every glyph
        # present in the UFO at that point; fixing up glyphs we're about to delete would
        # leave dangling category entries for glyphs no longer in this sparse master.
        for name in list(ufo.keys()):
            if name not in keep_glyphs:
                del ufo[name]
    with TTFont(font_path) as font:
        _fix_ufo(ufo, font)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ufo.save(str(dest))
    return ufo


def extract_static(otf: Path, dest_dir: Path) -> Path:
    """Decompile one static OTF into ``dest_dir/<font stem>.ufo`` and return that path."""
    dest = dest_dir / f"{otf.stem}.ufo"
    _extract(otf, dest)
    return dest


@dataclass(frozen=True)
class Master:
    """A master location in user coordinates; ``glyphs`` is None for a full master."""

    location: dict[str, float]
    glyphs: frozenset[str] | None

    @property
    def sparse(self) -> bool:
        return self.glyphs is not None

    def file_stem(self, family: str) -> str:
        parts = "-".join(f"{tag}{value:g}" for tag, value in sorted(self.location.items()))
        return f"{family}-{parts}"


def _to_user(font: TTFont, tag: str, normalized: float) -> float:
    axis = next((a for a in font["fvar"].axes if a.axisTag == tag), None)
    if axis is None:
        raise ValueError(f"no {tag!r} axis in fvar")
    if normalized >= 0:
        return axis.defaultValue + normalized * (axis.maxValue - axis.defaultValue)
    return axis.defaultValue + normalized * (axis.defaultValue - axis.minValue)


def _component_closure(font: TTFont, names: set[str]) -> frozenset[str]:
    glyf = font["glyf"]
    todo = list(names)
    closed = set(names)
    while todo:
        glyph = glyf[todo.pop()]
        if glyph.isComposite():
            for component in glyph.components:
                if component.glyphName not in closed:
                    closed.add(component.glyphName)
                    todo.append(component.glyphName)
    return frozenset(closed)


def variable_masters(font: TTFont) -> list[Master]:
    """Master locations implied by the gvar tuples: one full master per corner peak, plus
    sparse masters for glyphs that carry tuples peaking between the axis extremes."""
    if "avar" in font:
        raise NotImplementedError("avar mapping is not handled")
    tags = [a.axisTag for a in font["fvar"].axes]
    peaks: dict[tuple[tuple[str, float], ...], set[str]] = {}
    for name, variations in font["gvar"].variations.items():
        for variation in variations:
            peak = tuple(sorted((tag, variation.axes[tag][1]) for tag in variation.axes))
            peaks.setdefault(peak, set()).add(name)
    corners = {peak for peak in peaks if all(value in (-1.0, 1.0) for _, value in peak)}
    # Every intermediate master carries the same glyph set. If a glyph were missing from one
    # of them, varLib would fit that glyph on a different master grid than the original and
    # its interpolation would drift between the intermediate locations.
    switch_glyphs = _component_closure(font, set().union(*(peaks[p] for p in set(peaks) - corners)))
    masters = [Master({tag: _to_user(font, tag, 0.0) for tag in tags}, None)]
    for peak in sorted(peaks):
        location = {tag: _to_user(font, tag, 0.0) for tag in tags}
        location.update({tag: _to_user(font, tag, value) for tag, value in peak})
        masters.append(Master(location, None if peak in corners else switch_glyphs))
    return masters


def _debug_name(name_table: table__n_a_m_e, name_id: int) -> str:
    value = name_table.getDebugName(name_id)
    if value is None:
        raise ValueError(f"name table has no record for name ID {name_id}")
    return value


def _axis_labels(font: TTFont) -> dict[str, list[AxisLabelDescriptor]]:
    """STAT labels reconstructed from the named instances, which are called e.g. '400 Italic'."""
    name = font["name"]
    labels: dict[str, list[AxisLabelDescriptor]] = {"wght": [], "ital": []}
    for instance in font["fvar"].instances:
        if instance.coordinates.get("ital", 0) == 0:
            weight = _debug_name(name, instance.subfamilyNameID).split()[0]
            labels["wght"].append(AxisLabelDescriptor(name=weight, userValue=instance.coordinates["wght"]))
    labels["ital"] = [
        AxisLabelDescriptor(name="Regular", userValue=0),
        AxisLabelDescriptor(name="Italic", userValue=1),
    ]
    return labels


def extract_variable(vf_path: Path, dest_dir: Path, family: str) -> Path:
    """Instance the masters out of the variable font, extract them to UFOs, and write
    ``dest_dir/<family>.designspace``. Returns the designspace path."""
    font = TTFont(vf_path)
    name_table = font["name"]
    masters = variable_masters(font)
    stems = [master.file_stem(family) for master in masters]
    collisions = {stem for stem in stems if stems.count(stem) > 1}
    if collisions:
        # file_stem formats each axis value with limited precision (see Master.file_stem);
        # two distinct locations rounding to the same stem would silently overwrite one
        # master's UFO with another's.
        raise ValueError(f"master file stems collide: {sorted(collisions)}")
    dest_dir.mkdir(parents=True, exist_ok=True)

    doc = DesignSpaceDocument()
    labels = _axis_labels(font)
    for axis in font["fvar"].axes:
        descriptor = AxisDescriptor()
        descriptor.tag = axis.axisTag
        descriptor.name = _debug_name(name_table, axis.axisNameID)
        descriptor.minimum, descriptor.default, descriptor.maximum = (
            axis.minValue,
            axis.defaultValue,
            axis.maxValue,
        )
        descriptor.axisLabels = labels.get(axis.axisTag, [])
        doc.addAxis(descriptor)
    axis_names = {axis.tag: axis.name for axis in doc.axes}

    for master in masters:
        instance = instancer.instantiateVariableFont(font, master.location, inplace=False, updateFontNames=False)
        ttf_path = dest_dir / f"{master.file_stem(family)}.ttf"
        instance.save(ttf_path)
        ufo_path = dest_dir / f"{master.file_stem(family)}.ufo"
        try:
            _extract(ttf_path, ufo_path, keep_glyphs=master.glyphs)
        finally:
            ttf_path.unlink()
        source = SourceDescriptor()
        source.path = str(ufo_path)
        source.name = master.file_stem(family)
        source.familyName = family
        source.location = {axis_names[tag]: value for tag, value in master.location.items()}
        doc.addSource(source)

    for fvar_instance in font["fvar"].instances:
        instance_descriptor = InstanceDescriptor()
        instance_descriptor.familyName = family
        instance_descriptor.styleName = _debug_name(name_table, fvar_instance.subfamilyNameID)
        instance_descriptor.postScriptFontName = f"{family}-{instance_descriptor.styleName.replace(' ', '')}"
        instance_descriptor.location = {axis_names[tag]: value for tag, value in fvar_instance.coordinates.items()}
        doc.addInstance(instance_descriptor)

    designspace = dest_dir / f"{family}.designspace"
    doc.write(str(designspace))
    return designspace


def describe_masters(vf_path: Path) -> list[str]:
    """Human-readable master list, for ``cmfont info``."""
    font = TTFont(vf_path)
    lines = []
    for master in variable_masters(font):
        where = ", ".join(f"{tag}={value:g}" for tag, value in master.location.items())
        kind = f"sparse, {len(master.glyphs or ())} glyphs" if master.sparse else "full"
        lines.append(f"{where} ({kind})")
    return lines


def main(argv: list[str]) -> None:
    """``python -m commitmono_tools.extract FONT DEST_DIR``: worker for parallel extraction."""
    font, dest_dir = argv
    print(extract_static(Path(font), Path(dest_dir)))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])


__all__ = [
    "Master",
    "describe_masters",
    "extract_static",
    "extract_variable",
    "variable_masters",
]
