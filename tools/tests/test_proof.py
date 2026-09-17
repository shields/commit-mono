from pathlib import Path

from commitmono_tools import paths, proof


def test_shaping_applies_features(tmp_path: Path) -> None:
    proofer = proof.Proofer(paths.static_fonts({"400Regular"})[0])
    plain = [g.name for g in proofer.shape("a*", {})]
    lifted = [g.name for g in proofer.shape("a*", {"cv09": 1})]
    assert plain == ["a", "asterisk"]
    assert lifted == ["a", "asterisk.cv09"]
    svg = proofer.svg([proof.Line("test", "a*", {"cv09": 1})])
    assert svg.count("<path") == 2
    (tmp_path / "proof.svg").write_text(svg)


def test_variable_font_location() -> None:
    proofer = proof.Proofer(paths.variable_font(), {"wght": 700, "ital": 1})
    assert [g.name for g in proofer.shape("H", {})] == ["H"]
    assert proofer.path("H")


def test_feature_spec_parsing() -> None:
    assert proof.parse_features("ss01, cv09=2,-ss03") == {"ss01": 1, "cv09": 2, "ss03": 0}
    assert proof.parse_location("wght=400,ital=0.5") == {"wght": 400.0, "ital": 0.5}
