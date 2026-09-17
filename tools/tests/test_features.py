from fontTools.ttLib import TTFont

from commitmono_tools import features, paths


def test_website_catalog_matches_binary_features() -> None:
    catalog = features.website_catalog(paths.WEBSITE_DATA)
    font = TTFont(paths.static_fonts({"400Regular"})[0])
    tags = {feature.tag for feature in features.gsub_features(font)}
    assert set(catalog) == tags
    assert catalog["cv09"].label == "Lifted *"
    assert catalog["ss03"].default_on is True


def test_character_variants_are_single_substitutions() -> None:
    font = TTFont(paths.static_fonts({"400Regular"})[0])
    by_tag = {feature.tag: feature for feature in features.gsub_features(font)}
    cv09 = by_tag["cv09"]
    assert [lookup.kind for lookup in cv09.lookups] == ["single substitution"]
    assert "asterisk → asterisk.cv09" in cv09.lookups[0].rules
    kinds = {lookup.kind for feature in by_tag.values() for lookup in feature.lookups}
    assert "alternate substitution" not in kinds


def test_markdown_reference_renders() -> None:
    catalog = features.website_catalog(paths.WEBSITE_DATA)
    text = features.render_markdown(paths.static_fonts({"400Regular"})[0], catalog)
    assert "## cv09 — Lifted *" in text
    assert "| `.cv09` |" in text
