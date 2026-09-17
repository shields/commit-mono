"""Extracting and rebuilding the shipped binaries must reproduce them."""

from pathlib import Path

import pytest

from commitmono_tools import build, extract, paths, verify

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("style", ["400Regular", "400Italic"])
def test_static_round_trip(tmp_path: Path, style: str) -> None:
    original = paths.static_fonts({style})[0]
    ufo = extract.extract_static(original, tmp_path / "sources")
    built = build.build_static(ufo, tmp_path / "fonts")
    report = verify.verify_static(original, built)
    assert report.ok, report.render()


def test_variable_round_trip(tmp_path: Path) -> None:
    original = paths.variable_font()
    designspace = extract.extract_variable(original, tmp_path / "sources", paths.family_name())
    built = build.build_variable(designspace, tmp_path / "fonts")
    report = verify.verify_variable(original, built)
    assert report.ok, report.render()
