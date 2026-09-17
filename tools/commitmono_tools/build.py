"""Compile UFO sources back into binaries with fontmake."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _fontmake(args: list[str], verbose: bool) -> None:
    command = [sys.executable, "-m", "fontmake", *args]
    result = subprocess.run(command, capture_output=not verbose, text=True, check=False)
    if result.returncode != 0:
        output = "" if verbose else f"\n{result.stdout}\n{result.stderr}"
        raise RuntimeError(f"fontmake failed: {' '.join(command)}{output}")


def static_output_path(ufo: Path, out_dir: Path) -> Path:
    """Where ``build_static`` writes ``ufo``'s compiled OTF, without actually building it."""
    return out_dir / f"{ufo.stem}.otf"


def variable_output_path(designspace: Path, out_dir: Path) -> Path:
    """Where ``build_variable`` writes ``designspace``'s compiled TTF, without building it."""
    return out_dir / f"{designspace.stem}-VF.ttf"


def build_static(ufo: Path, out_dir: Path, verbose: bool = False) -> Path:
    """Compile a cubic UFO to ``out_dir/<ufo stem>.otf``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # The shipped outlines keep their overlapping contours; fontmake would otherwise merge them.
    _fontmake(["-u", str(ufo), "-o", "otf", "--keep-overlaps", "--output-dir", str(out_dir)], verbose)
    return static_output_path(ufo, out_dir)


def build_variable(designspace: Path, out_dir: Path, verbose: bool = False) -> Path:
    """Compile a designspace of TrueType masters to ``out_dir/<designspace stem>-VF.ttf``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # The masters were extracted from TrueType, so their contours already run clockwise;
    # without --keep-direction ufo2ft would reverse every contour a second time.
    _fontmake(
        ["-m", str(designspace), "-o", "variable", "--keep-direction", "--output-dir", str(out_dir)],
        verbose,
    )
    return variable_output_path(designspace, out_dir)
