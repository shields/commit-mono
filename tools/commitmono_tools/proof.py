"""Render proof sheets as SVG: text shaped with HarfBuzz, outlines drawn with fontTools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

Features = dict[str, int]


@dataclass(frozen=True)
class Line:
    label: str
    text: str
    features: Features


@dataclass
class _Glyph:
    name: str
    x: float
    y: float


class Proofer:
    """Shapes and draws text with one font, optionally at a variable-font location."""

    def __init__(self, font_path: Path, location: dict[str, float] | None = None) -> None:
        self.font = TTFont(font_path)
        if location and "fvar" not in self.font:
            # getGlyphSet(location=...) and hb's set_variations() both silently ignore a
            # location on a non-variable font instead of raising; catch it here so a
            # mismatched --font/--location combination fails loudly instead of quietly
            # rendering the unvaried font.
            raise ValueError(f"{font_path} has no fvar table; a location has no effect on it")
        self.upm = self.font["head"].unitsPerEm
        self.location = location or {}
        self.glyph_set = self.font.getGlyphSet(location=self.location or None)
        face = hb.Face(font_path.read_bytes())
        self.hb_font = hb.Font(face)
        self.hb_font.scale = (self.upm, self.upm)
        if self.location:
            self.hb_font.set_variations(self.location)
        self._paths: dict[str, str] = {}

    def shape(self, text: str, features: Features) -> list[_Glyph]:
        buffer = hb.Buffer()
        buffer.add_str(text)
        buffer.guess_segment_properties()
        hb.shape(self.hb_font, buffer, features)
        order = self.font.getGlyphOrder()
        glyphs = []
        x = y = 0.0
        for info, pos in zip(buffer.glyph_infos, buffer.glyph_positions, strict=True):
            glyphs.append(_Glyph(order[info.codepoint], x + pos.x_offset, y + pos.y_offset))
            x += pos.x_advance
            y += pos.y_advance
        return glyphs

    def path(self, name: str) -> str:
        if name not in self._paths:
            pen = SVGPathPen(self.glyph_set)
            self.glyph_set[name].draw(pen)
            self._paths[name] = pen.getCommands()
        return self._paths[name]

    def svg(self, lines: list[Line], size: float = 40, label_width: float = 300) -> str:
        scale = size / self.upm
        line_height = size * 1.6
        width = 0.0
        body: list[str] = []
        for row, line in enumerate(lines):
            baseline = (row + 1) * line_height
            body.append(
                f'<text x="0" y="{baseline:.1f}" font-family="monospace" font-size="{size * 0.35:.1f}">'
                f"{escape(line.label)}</text>"
            )
            for glyph in self.shape(line.text, line.features):
                d = self.path(glyph.name)
                if not d:
                    continue
                tx = label_width + glyph.x * scale
                ty = baseline - glyph.y * scale
                body.append(f'<path transform="translate({tx:.2f} {ty:.2f}) scale({scale:.5f} {-scale:.5f})" d="{d}"/>')
                width = max(width, tx + 2 * size)
        height = (len(lines) + 0.5) * line_height
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
            f'viewBox="0 0 {width:.0f} {height:.0f}" fill="black">\n' + "\n".join(body) + "\n</svg>\n"
        )


def parse_features(spec: str) -> Features:
    """``ss01,cv09=2,-ss03`` → ``{"ss01": 1, "cv09": 2, "ss03": 0}``."""
    features: Features = {}
    for item in filter(None, (s.strip() for s in spec.split(","))):
        if item.startswith("-"):
            tag = item[1:].strip()
            if "=" in tag:
                raise ValueError(f"invalid feature spec {item!r}: cannot combine '-' with '='")
            features[_tag(tag, item)] = 0
        elif "=" in item:
            tag, value = item.split("=", 1)
            tag, value = _tag(tag.strip(), item), value.strip()
            try:
                features[tag] = int(value)
            except ValueError:
                raise ValueError(f"invalid feature spec {item!r}: {value!r} is not an integer") from None
        else:
            features[item] = 1
    return features


def _tag(tag: str, item: str) -> str:
    if not tag:
        raise ValueError(f"invalid spec {item!r}: missing tag")
    return tag


def parse_location(spec: str) -> dict[str, float]:
    """``wght=400,ital=0`` → ``{"wght": 400.0, "ital": 0.0}``."""
    location = {}
    for item in filter(None, (s.strip() for s in spec.split(","))):
        if "=" not in item:
            raise ValueError(f"invalid location {item!r}: expected TAG=VALUE")
        tag, value = item.split("=", 1)
        location[_tag(tag.strip(), item)] = float(value.strip())
    return location


def feature_matrix(catalog_examples: dict[str, tuple[str, str]], feature_test_text: str) -> list[Line]:
    """Each catalogued feature off and on with its website example, then the feature test text."""
    lines = []
    for tag, (label, example) in catalog_examples.items():
        lines.append(Line(f"{tag} off  {label}", example, {tag: 0}))
        lines.append(Line(f"{tag} on", example, {tag: 1}))
    for text in feature_test_text.splitlines():
        if text.strip():
            lines.append(Line("featuretest", text, {}))
    return lines
