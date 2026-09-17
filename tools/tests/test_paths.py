from commitmono_tools import paths


def test_shipped_binaries_are_found() -> None:
    assert paths.version_tag() == "V143"
    fonts = paths.static_fonts()
    assert len(fonts) == 42
    assert paths.style_of(fonts[0]) == (200, False)
    assert paths.style_name(*paths.style_of(fonts[-1])) == "700Italic"
    assert paths.static_fonts({"400Regular"})[0].name == "CommitMonoV143-400Regular.otf"
    assert paths.variable_font().exists()
