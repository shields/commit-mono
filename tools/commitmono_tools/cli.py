"""Command line entry point: ``cmfont <command>``."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fontTools.ttLib import TTFont

from . import build, extract, features, paths, proof, verify


def _styles(value: str | None) -> set[str] | None:
    if value is None:
        return None
    styles = {s.strip() for s in value.split(",") if s.strip()}
    if not styles:
        # An empty result (e.g. "--only ,") is not "no filter": paths.static_fonts()
        # treats a non-None, empty set as "match nothing" and its unknown-style check
        # never fires on an empty set, so this would otherwise silently process 0 fonts.
        raise ValueError(f"--only {value!r} contains no style names")
    return styles


def _jobs(value: str) -> int:
    jobs = int(value)
    if jobs < 1:
        raise argparse.ArgumentTypeError(f"--jobs must be at least 1, got {jobs}")
    return jobs


def _selection(args: argparse.Namespace) -> tuple[bool, bool]:
    # --only names static styles, so it implies --static unless --variable is also given.
    only_static = args.static or bool(args.only)
    both = not (only_static or args.variable)
    return only_static or both, args.variable or both


def _run_parallel[T](jobs: int, function: Callable[[Path], T], items: list[Path]) -> list[T]:
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(function, items))


def cmd_extract(args: argparse.Namespace) -> int:
    do_static, do_variable = _selection(args)
    if do_static:
        fonts = paths.static_fonts(_styles(args.only))
        print(f"extracting {len(fonts)} static fonts to {paths.STATIC_SOURCES_DIR}")
        _run_parallel(args.jobs, _extract_static, fonts)
    if do_variable:
        print(f"extracting variable font masters to {paths.VARIABLE_SOURCES_DIR}")
        designspace = extract.extract_variable(paths.variable_font(), paths.VARIABLE_SOURCES_DIR, paths.family_name())
        print(f"wrote {designspace}")
    return 0


def _extract_static(font: Path) -> Path:
    # A subprocess per font: extraction is CPU-bound Python, and multiprocessing's
    # semaphores are unavailable in some sandboxes.
    command = [sys.executable, "-m", "commitmono_tools.extract", str(font), str(paths.STATIC_SOURCES_DIR)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"extraction failed for {font.name}:\n{result.stderr}")
    return paths.static_source(font)


def _build_static(ufo: Path) -> Path:
    return build.build_static(ufo, paths.FONTS_OUT_DIR)


def cmd_build(args: argparse.Namespace) -> int:
    do_static, do_variable = _selection(args)
    ok = True
    if do_static:
        ufos = [paths.static_source(font) for font in paths.static_fonts(_styles(args.only))]
        missing = [u for u in ufos if not u.exists()]
        if missing:
            print(f"missing sources, run `cmfont extract` first: {[m.name for m in missing]}", file=sys.stderr)
            ok = False
        else:
            print(f"building {len(ufos)} static fonts into {paths.FONTS_OUT_DIR}")
            if args.verbose:
                # Serial, so fontmake's output isn't interleaved across fonts; still attempt
                # every font before failing, matching the parallel branch's behavior below.
                failures = []
                for ufo in ufos:
                    try:
                        build.build_static(ufo, paths.FONTS_OUT_DIR, verbose=True)
                    except RuntimeError as exc:
                        failures.append(str(exc))
                if failures:
                    raise RuntimeError("\n".join(failures))
            else:
                _run_parallel(args.jobs, _build_static, ufos)
    if do_variable:
        designspace = paths.variable_designspace()
        if not designspace.exists():
            print(f"missing {designspace}, run `cmfont extract --variable` first", file=sys.stderr)
            ok = False
        else:
            print(f"building variable font into {paths.FONTS_OUT_DIR}")
            built = build.build_variable(designspace, paths.FONTS_OUT_DIR, verbose=args.verbose)
            print(f"wrote {built}")
    return 0 if ok else 1


def cmd_verify(args: argparse.Namespace) -> int:
    do_static, do_variable = _selection(args)
    reports: list[verify.Report] = []
    ok = True
    if do_static:
        for original in paths.static_fonts(_styles(args.only)):
            built = build.static_output_path(paths.static_source(original), paths.FONTS_OUT_DIR)
            if not built.exists():
                print(f"missing {built}, run `cmfont build` first", file=sys.stderr)
                ok = False
                continue
            reports.append(verify.verify_static(original, built, args.tolerance))
            print(reports[-1].render())
    if do_variable:
        original = paths.variable_font()
        built = build.variable_output_path(paths.variable_designspace(), paths.FONTS_OUT_DIR)
        if not built.exists():
            print(f"missing {built}, run `cmfont build --variable` first", file=sys.stderr)
            ok = False
        else:
            reports.append(verify.verify_variable(original, built, args.tolerance))
            print(reports[-1].render())
    failed = [r.name for r in reports if not r.ok]
    summary = f"\n{len(reports) - len(failed)} of {len(reports)} fonts verified"
    print(summary + (f", failed: {failed}" if failed else ""))
    return 1 if failed or not ok else 0


def _font_argument(value: str | None, default: Callable[[], Path]) -> Path:
    # `default` is a thunk so an explicit --font never pays for resolving the fallback
    # (e.g. autodetecting the shipped binaries' version tag, which can fail on its own).
    return Path(value).resolve() if value else default()


def _default_static() -> Path:
    return paths.static_fonts({"400Regular"})[0]


def cmd_features(args: argparse.Namespace) -> int:
    font = _font_argument(args.font, _default_static)
    catalog = features.website_catalog(paths.WEBSITE_DATA)
    text = features.render_markdown(font, catalog)
    if args.write is None:
        print(text, end="")
        return 0
    target = Path(args.write) if args.write else paths.DOCS_DIR / "features.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}")
    return 0


def cmd_proof(args: argparse.Namespace) -> int:
    location = proof.parse_location(args.location) if args.location else None
    # A location only means anything on the variable font; defaulting to a static font
    # would silently ignore it.
    default_font = paths.variable_font if location else _default_static
    font = _font_argument(args.font, default_font)
    proofer = proof.Proofer(font, location)
    if args.text:
        selected = proof.parse_features(args.features or "")
        lines = [proof.Line(args.features or "default", text, selected) for text in args.text]
        suffix = "proof"
    else:
        catalog = features.website_catalog(paths.WEBSITE_DATA)
        examples = {tag: (entry.label, entry.example) for tag, entry in catalog.items()}
        lines = proof.feature_matrix(examples, paths.FEATURE_TEST_TEXT.read_text(encoding="utf-8"))
        suffix = "features"
    where = "-" + "-".join(f"{tag}{value:g}" for tag, value in (location or {}).items()) if location else ""
    target = Path(args.out) if args.out else paths.PROOFS_DIR / f"{font.stem}{where}-{suffix}.svg"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not args.out and target.exists():
        # Two --location values that round to the same {value:g} string (see the analogous
        # collision check on Master.file_stem in extract.py) would otherwise silently
        # overwrite each other's proof.
        print(f"warning: overwriting existing {target}", file=sys.stderr)
    target.write_text(proofer.svg(lines), encoding="utf-8")
    print(f"wrote {target}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    font_path = _font_argument(args.font, paths.variable_font)
    font = TTFont(font_path)
    print(f"{font_path.name}: {len(font.getGlyphOrder())} glyphs, {font['head'].unitsPerEm} upm")
    # TTFont has no __iter__, only keys()/__getitem__/__contains__: `for t in font` falls
    # back to the legacy __getitem__(int) iteration protocol and crashes. Keep .keys().
    print("tables:", " ".join(sorted(t for t in font.keys() if t != "GlyphOrder")))  # noqa: SIM118
    for table in ("GSUB", "GPOS"):
        if table in font:
            tags = sorted({r.FeatureTag for r in font[table].table.FeatureList.FeatureRecord})
            print(f"{table} features: {' '.join(tags) or '(none)'}")
    if "fvar" in font:
        for axis in font["fvar"].axes:
            print(f"axis {axis.axisTag}: {axis.minValue:g} to {axis.maxValue:g}, default {axis.defaultValue:g}")
        print(f"named instances: {len(font['fvar'].instances)}")
        print("masters implied by gvar:")
        for line in extract.describe_masters(font_path):
            print(f"  {line}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cmfont", description="Commit Mono font tooling")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_selection(p: argparse.ArgumentParser) -> None:
        p.add_argument("--static", action="store_true", help="only the static OTFs")
        p.add_argument("--variable", action="store_true", help="only the variable font")
        p.add_argument("--only", help="comma-separated static styles, e.g. 400Regular,700Italic")

    p = sub.add_parser("extract", help="decompile the shipped binaries into UFO sources under build/")
    add_selection(p)
    p.add_argument("--jobs", type=_jobs, default=os.cpu_count() or 1)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("build", help="compile the UFO sources with fontmake into build/fonts/")
    add_selection(p)
    p.add_argument("--jobs", type=_jobs, default=os.cpu_count() or 1)
    p.add_argument("--verbose", action="store_true", help="show fontmake output")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help="compare build/fonts/ against the shipped binaries")
    add_selection(p)
    p.add_argument("--tolerance", type=float, default=verify.DEFAULT_TOLERANCE, help="max outline deviation in units")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("features", help="describe the GSUB features of a binary as Markdown")
    p.add_argument("--font", help="font to describe (default: the shipped 400 Regular)")
    p.add_argument("--write", nargs="?", const="", help="write to docs/features.md or the given path")
    p.set_defaults(func=cmd_features)

    p = sub.add_parser("proof", help="render an SVG proof sheet into build/proofs/")
    p.add_argument("--font", help="font to render (default: the shipped 400 Regular)")
    p.add_argument("--location", help="variable font location, e.g. wght=400,ital=0")
    p.add_argument("--text", action="append", help="line to render; repeatable. Default: feature matrix")
    p.add_argument("--features", help="feature spec for --text lines, e.g. ss01,cv09=1,-ss03")
    p.add_argument("--out", help="output path")
    p.set_defaults(func=cmd_proof)

    p = sub.add_parser("info", help="summarize a binary (default: the variable font)")
    p.add_argument("--font")
    p.set_defaults(func=cmd_info)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        # The tool's own deliberate failures (bad arguments, missing inputs, fontmake errors).
        print(f"cmfont: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
