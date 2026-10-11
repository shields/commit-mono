# Building, verifying and proofing

The `tools/` directory is a Python 3.15 [uv](https://docs.astral.sh/uv/) project that provides the
`cmfont` command. It needs no font editor: it decompiles the shipped binaries into UFO
sources with `ufo-extractor`, compiles them back with `fontmake`, and checks the result
against the originals with fontTools. Shaping for proofs uses HarfBuzz.

```sh
cd tools
uv sync --group dev
uv run cmfont --help
```

## Commands

| Command | What it does |
|---|---|
| `cmfont info [--font PATH]` | Summarize a binary: tables, features, axes, instances, and the masters implied by the variable font's `gvar`. |
| `cmfont extract [--static] [--variable] [--only 400Regular,700Italic] [--jobs N]` | Decompile the shipped binaries into `build/sources/`. |
| `cmfont build [--static] [--variable] [--only …] [--verbose] [--jobs N]` | Compile the sources with fontmake into `build/fonts/`. |
| `cmfont verify [--static] [--variable] [--only …] [--tolerance 1.0]` | Compare `build/fonts/` with `src/fonts/fontlab/` and exit non-zero on any difference beyond the tolerance. |
| `cmfont features [--font PATH] [--write [PATH]]` | Render the GSUB features as Markdown; `--write` updates `docs/features.md`. |
| `cmfont proof [--font PATH] [--location wght=400,ital=0] [--text … --features …] [--out PATH]` | Render an SVG proof sheet into `build/proofs/`. Without `--text` it renders every catalogued feature off and on with the website's example, followed by `src/txt/featuretest.txt`. |
| `uv run pytest`, `uv run ruff check .` | Tests (including a slow round trip of two statics and the variable font) and lint. |

A full round trip over all 43 binaries takes about a minute on a laptop:

```sh
uv run cmfont extract && uv run cmfont build && uv run cmfont verify
```

## What `extract` produces

`build/sources/static/<font>.ufo`, one cubic UFO per static font. Each contains all 1932
glyphs, the font info from the binary's `name`, `OS/2`, `hhea` and `post` tables, and a
`features.fea` decompiled from the GSUB table (73 lookups, with generated lookup names).

`build/sources/variable/`: eight TrueType-flavoured master UFOs and
`CommitMonoV143.designspace`. The masters are instanced out of the shipped variable font at
the locations its `gvar` tuples imply: four full masters at the corners and four sparse
masters (81 glyphs each) at `ital` 0.5 and 0.51. The designspace carries the two axes, the
42 named instances and the STAT labels. Every sparse master holds the same glyph set on
purpose: if one of them lacked a glyph, varLib would fit that glyph on a different master
grid and it would drift between the intermediate locations.

Fixups applied to every extracted UFO, because `ufo-extractor` alone does not round-trip:

- It writes an empty `table GDEF {}` block into `features.fea`, which stops ufo2ft from
  generating the real GDEF. The block is removed and the glyph classes are carried in
  `public.openTypeCategories` instead.
- `openTypeOS2Selection` is filled from the binary's `fsSelection` so bit 7
  (USE_TYPO_METRICS) survives.
- TrueType instruction hashes in the glyph libs are dropped; they never match a rebuilt
  glyph and only produce warnings.

## What `build` does

Statics: `fontmake -u <ufo> -o otf --keep-overlaps`. The shipped outlines keep their
overlapping contours, and fontmake would otherwise merge them and change 387 glyphs.

Variable font: `fontmake -m <designspace> -o variable --keep-direction`. The masters were
extracted from TrueType, so their contours already run clockwise; without the flag ufo2ft
reverses every contour a second time.

## What `verify` checks, and the expected result

For each glyph: identical outline structure, points within the tolerance (default 1 unit),
identical advance width, and a left side bearing within 6 units (the largest deviation the
shipped binaries are known to produce, see below). For the tables: every cmap subtable,
GSUB and GPOS feature tags and lookup counts, GDEF classes, the metrics fields of `hhea`,
`OS/2`, `head` and `post`, name IDs 1, 2, 4, 6, 16 and 17, and the set of tables (a table
the rebuild adds is a failure; one it drops is a note). The variable font is additionally instanced at ten locations,
including the switch region around `ital` 0.5, and its named instances, `STAT`, `MVAR`,
`HVAR` and `gvar` presence are compared.

Against the shipped binaries the rebuild is faithful:

- All 42 statics reproduce their outlines exactly, fractional italic coordinates included.
- The variable font matches within 1 unit at every test location.
- Reported as notes, not failures: `DSIG` (empty) and `GPOS` (no features) are not
  rebuilt, and neither is the legacy Macintosh cmap subtable; about 200 glyphs per italic static differ in left side bearing by 1 unit, because
  the originals store a side bearing that does not match the rounded fractional `xMin`; the
  variable font's italic composites differ in left side bearing by up to 6 units, which is
  the phantom-point quirk described in [font-internals.md](font-internals.md); Regular
  statics gain name ID 16.

## Making changes

Nothing in the tooling changes letterforms or spacing. When that is wanted, the intended
flow is:

1. `cmfont extract` to get fresh sources.
2. Edit the UFOs. For scripted edits, defcon plus fontTools pens are enough; for example,
   moving a glyph is `glyph.move((0, 60))`, and a rotation about the bounding-box centre is
   a `TransformPen` replay. A UFO editor such as Fontra or FontForge also works. Edit the
   static sources and the four corner masters of the variable font consistently; the sparse
   masters only matter for the 81 switch glyphs. In the variable masters the `.case`,
   `.c2_*`, `.c3_*` and smart-kerning variants are composites and follow their base glyph;
   in the static sources they are separate outlines and need the same edit.
3. `cmfont build`, then `cmfont verify` to confirm that only the intended glyphs changed
   (the report names them), and `cmfont proof` to look at the result.
4. Copy `build/fonts/*.otf` over `src/fonts/fontlab/` and run the website
   (`bun install && bun run dev`) to produce customized downloads with the wizard, or install
   the rebuilt fonts directly.

Keep the `--keep-overlaps` and `--keep-direction` behaviour when adding build options, and
regenerate `docs/features.md` whenever the layout rules change.
