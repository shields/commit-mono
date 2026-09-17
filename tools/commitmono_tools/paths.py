"""Repository locations and the naming conventions of the shipped font binaries."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FONT_DIR = REPO / "src" / "fonts" / "fontlab"
WEBSITE_DATA = REPO / "src" / "js" / "website_data.js"
FEATURE_TEST_TEXT = REPO / "src" / "txt" / "featuretest.txt"
DOCS_DIR = REPO / "docs"

BUILD_DIR = REPO / "build"
STATIC_SOURCES_DIR = BUILD_DIR / "sources" / "static"
VARIABLE_SOURCES_DIR = BUILD_DIR / "sources" / "variable"
FONTS_OUT_DIR = BUILD_DIR / "fonts"
PROOFS_DIR = BUILD_DIR / "proofs"

_STATIC_RE = re.compile(r"^CommitMono(V\d+)-(\d+)(Regular|Italic)\.otf$")


def version_tag() -> str:
    """Version tag embedded in the binary file names, e.g. ``V143``."""
    candidates = sorted(FONT_DIR.glob("CommitMonoV*-VF.ttf"))
    if len(candidates) != 1:
        raise FileNotFoundError(f"expected exactly one CommitMonoV*-VF.ttf in {FONT_DIR}, found {candidates}")
    return candidates[0].name.removeprefix("CommitMono").removesuffix("-VF.ttf")


def family_name() -> str:
    return f"CommitMono{version_tag()}"


def variable_font() -> Path:
    return FONT_DIR / f"{family_name()}-VF.ttf"


def style_of(path: Path) -> tuple[int, bool]:
    """Weight and italic flag of a static binary, from its file name."""
    match = _STATIC_RE.match(path.name)
    if match is None:
        raise ValueError(f"not a Commit Mono static font: {path.name}")
    return int(match.group(2)), match.group(3) == "Italic"


def style_name(weight: int, italic: bool) -> str:
    return f"{weight}{'Italic' if italic else 'Regular'}"


def static_fonts(only: set[str] | None = None) -> list[Path]:
    """All shipped static OTFs for the current version tag, optionally filtered to style
    names such as ``400Regular``."""
    tag = version_tag()
    matches = [(p, m) for p in FONT_DIR.glob("CommitMono*.otf") if (m := _STATIC_RE.match(p.name))]
    stale = sorted(p.name for p, m in matches if m.group(1) != tag)
    if stale:
        # variable_font() hard-fails on a version mismatch; a stray static from another
        # version sitting alongside the current set should be just as loud, not silently
        # folded into "the shipped statics".
        raise ValueError(f"static fonts with a version other than {tag}: {stale}")
    fonts = [p for p, m in matches if m.group(1) == tag]
    fonts.sort(key=style_of)
    if only is not None:
        fonts = [p for p in fonts if style_name(*style_of(p)) in only]
        missing = only - {style_name(*style_of(p)) for p in fonts}
        if missing:
            raise ValueError(f"unknown styles: {sorted(missing)}")
    return fonts


def static_source(font: Path) -> Path:
    return STATIC_SOURCES_DIR / f"{font.stem}.ufo"


def variable_designspace() -> Path:
    return VARIABLE_SOURCES_DIR / f"{family_name()}.designspace"
