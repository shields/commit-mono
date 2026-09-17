# Inside the font binaries

All numbers below come from `CommitMonoV143` and were measured with fontTools. Run
`cmfont info` for a live summary of the variable font, or `cmfont info --font <path>` for a
static one.

## Common properties

- 1000 units per em, 1932 glyphs, and every glyph is exactly 600 units wide. The font has
  no kerning: all spacing effects are done by substituting pre-shifted glyph variants (see
  smart kerning and symbol spacing below).
- Layout is GSUB only. A GPOS table exists but contains no features. GDEF classifies 14
  glyphs as ligatures and 6 as marks; no lookup uses these classes.
- The same 16 GSUB features (`cv01`–`cv11`, `ss01`–`ss05`) with the same 73 lookups are in
  every binary. There is no `calt` or `liga`; the website's wizard synthesizes `calt` from the
  `ss` features the user picks.
- No hinting tables (`fpgm`, `prep`, `cvt`, `gasp`). The release zip is hinted separately
  with ttfautohint.

## Static fonts

- CFF (cubic) outlines. The Regular fonts have integer coordinates. The Italic fonts were
  obliqued (`post.italicAngle` is −9.5°) and carry fractional coordinates; their `hmtx`
  side bearings do not always match the rounded outline `xMin` (`zeta` has `xMin` 77.17 and
  a side bearing of 76).
- Tables: `CFF `, `DSIG`, `GDEF`, `GPOS`, `GSUB`, `OS/2`, `cmap`, `head`, `hhea`, `hmtx`,
  `maxp`, `name`, `post`. `DSIG` is an empty placeholder and can be dropped.
- Names: family `CommitMonoV143`, style `Regular` or `Italic`, typographic subfamily such as
  `400 Regular`, PostScript name `CommitMonoV143-400Regular`. The wizard rewrites all of
  these to `CommitMono` plus Regular, Italic, Bold or Bold Italic.
- The 42 instances are not linear blends of the 200 and 700 fonts. Intermediate weights
  deviate from a straight blend by a few units on hundreds of glyphs, and 173 glyphs have
  different point structures between the corner instances (FontLab flattened overlaps
  differently per instance). The statics therefore cannot serve as masters for the variable
  font. For example, in 250 Regular the two counters of the 8 in `threeeighths`,
  `fiveeighths` and `seveneighths` are stored in the opposite order from the neighbouring
  weights: identical to look at, but not interpolable.

## Variable font

- TrueType outlines (`glyf`/`gvar`) with `HVAR`, `MVAR` and `STAT`. Axes: `wght` 200–700 and
  `ital` 0–1. The default location is `wght=200, ital=0`, not 400, which is unusual but
  harmless. 42 named instances mirror the statics ("200 Regular" … "700 Italic").
- Masters, as implied by the `gvar` tuples: four full masters at the corners
  (200/700 × upright/italic), plus four sparse masters at `ital` 0.5 and 0.51 (for both
  weights) covering 81 "switch" glyphs: the true-italic `a e f g y` forms behind `cv08`
  with their accented and smart-kerning variants, and the combining accents. Those glyphs
  snap from the slanted form to the italic form halfway along the italic axis instead of
  blending. Everything else interpolates linearly between the corners.
- Instanced at weights 200, 400 and 700 the variable font matches the static fonts to
  within 2.5 units (the cubic-to-quadratic conversion) and exactly on straight-sided glyphs
  such as `asterisk`, `grave` and `comma`.
- Composites are used throughout (accented letters, the `.case`, `.c2_*`, `.c3_*` and
  smart-kerning variants are components of their base glyph with an offset).
- Quirk: in the italic region, 329 composite glyphs (the smart-kerning variants of the
  capitals and the accented letters) carry phantom-point deltas that make their `hmtx` left
  side bearing disagree with the outline by up to 6 units. Because `head.flags` bit 1 is
  clear and `HVAR` has no side-bearing map, renderers honour that side bearing and draw the
  glyph up to 6 units to the right of its outline, so for instance `C.leftL` is shifted 40
  units left of `C` in the italic variable font but 44 in every static italic. The static
  italics show the outline position is the intended one; a rebuilt variable font uses the
  outline and matches them. This looks like a FontLab export artifact and has not been
  reported upstream.

## Glyph naming

Glyph names follow the FontLab project. Suffixes stack (`colon.case.square.c3_1`).

| Suffix | Meaning | Reached through |
|---|---|---|
| `.cv01` … `.cv11` | The alternate exposed by that character-variant feature | `cvNN` |
| `.case` | Form for use next to capitals (raised or recentered symbols) | `ss03` smart case |
| `.square` | Square instead of round dots | `cv03` |
| `.leftL/.leftM/.leftS`, `.rightL/.rightM/.rightS` | The glyph shifted left or right by a large, medium or small amount | `ss05` smart kerning |
| `.c2_1`, `.c2_2`, `.c3_1`, `.c3_3` | Position 1 or 2 of a two-symbol run, position 1 or 3 of a three-symbol run, moved toward the middle | `ss04` symbol spacing |
| `.liga` | Ligature glyphs such as `<=`, `!=`, `===` | `ss01` |
| `.numr`, `.dnom`, `.onum` | Numerator, denominator and old-style figures | Nothing: no feature exposes them and they have no code points, so they are unreachable |

## Features

Every character variant `cv01`–`cv11` is a single substitution with exactly one alternate
per glyph, so each is a plain on/off switch. The OpenType `cvNN` mechanism allows several
alternates selected by index (an alternate-substitution lookup, chosen with
`font-feature-settings: "cv09" 2` in CSS), but this font does not use it, and the wizard's
outline-swapping code only understands single substitutions.

`ss01` (ligatures) and `ss02` (arrows) are contextual rules that call ligature lookups
(`less_equal.liga` and friends) and single substitutions (arrow pieces). `ss03`, `ss04` and
`ss05` are chains of contextual rules that call single-substitution lookups to swap in the
`.case`, `.c2_*`/`.c3_*` and `.left*`/`.right*` variants. `ss03`, `ss04` and `ss05` are
on by default in the website's catalog. The full rule listing is in
[features.md](features.md).

## Known inconsistencies

- The `.fea` files in `src/features/` are stale relative to the binaries.
- Regular statics lack name ID 16 (typographic family) while the italics have it; a
  rebuild adds it consistently.
- Glyph names differ slightly between the statics and the variable font for ten glyphs
  (for example `gcommaaccent.cv02` versus `uni0123.cv02`, `uni0000` versus `.null`). The
  tooling keeps each binary's own names.
