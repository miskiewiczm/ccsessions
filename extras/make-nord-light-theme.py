#!/usr/bin/env python3
"""Derive a light Nord syntax-highlighting theme from the one Quarto ships.

Quarto bundles a dark `nord.theme` but no light counterpart. Rather than
redistribute a modified copy of it, this script reads the file from the local
Quarto installation and writes `nord-light.theme` into the current directory,
keeping every Nord hue and only lowering lightness enough to read on a Snow
Storm background.

Run it in the directory that holds the document you are rendering: Quarto
resolves custom `highlight-style` files relative to the document, and silently
ignores absolute paths.

    cd path/to/your/transcripts && python3 extras/make-nord-light-theme.py
"""

from __future__ import annotations

import argparse
import colorsys
import json
import pathlib
import shutil
import sys

CANDIDATES = (
    "/Applications/quarto/share/pandoc/highlight-styles/nord.theme",
    "/usr/local/share/quarto/pandoc/highlight-styles/nord.theme",
    "/usr/share/quarto/pandoc/highlight-styles/nord.theme",
)

NORD0, NORD1, NORD5, NORD6 = "#2e3440", "#3b4252", "#e5e9f0", "#eceff4"


def find_source() -> pathlib.Path:
    for path in CANDIDATES:
        if pathlib.Path(path).is_file():
            return pathlib.Path(path)
    quarto = shutil.which("quarto")
    if quarto:  # follow the launcher back to its share/ tree
        guess = pathlib.Path(quarto).resolve().parent.parent / "share/pandoc/highlight-styles/nord.theme"
        if guess.is_file():
            return guess
    sys.exit("nord.theme not found — is Quarto installed?")


def darken(color: object, floor: float = 0.42) -> object:
    """Keep the hue, cap the lightness, nudge saturation to compensate."""
    if not (isinstance(color, str) and color.startswith("#") and len(color) == 7):
        return color
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, min(l, floor), min(1.0, s * 1.15))
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in (r, g, b))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--output", default="nord-light.theme", type=pathlib.Path)
    args = ap.parse_args()

    theme = json.loads(find_source().read_text(encoding="utf-8"))
    theme["background-color"] = NORD6
    theme["text-color"] = NORD0
    for style in theme.get("text-styles", {}).values():
        style["text-color"] = darken(style.get("text-color"))
        if style.get("background-color"):
            style["background-color"] = NORD5
    args.output.write_text(json.dumps(theme, indent=2), encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()
