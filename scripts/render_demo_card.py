"""Render `loci demo` output as the README card image.

Runs the real command, captures stdout, and paints it into a terminal-style
PNG — the text in the image is exactly what the tool prints, so the card can
not drift from the product. Deterministic apart from the per-query timings,
which are sub-millisecond and therefore dull; they are blanked out.

    python scripts/render_demo_card.py
    → docs/assets/demo-offline.png
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "demo-offline.png"

SCALE = 2                     # supersample, then downscale for crisp glyphs
FONT_SIZE = 13 * SCALE
PAD = 26 * SCALE
LINE_H = 21 * SCALE
HEADER_H = 38 * SCALE
MAX_CHARS = 116               # wrap instead of truncating: no text is lost
MIN_WIDTH = 760

BG = (13, 17, 23)
CARD = (22, 27, 34)
BORDER = (48, 54, 61)
TITLE = (139, 148, 158)
TEXT = (201, 209, 217)
DIM = (125, 133, 144)
GREEN = (63, 185, 80)
BLUE = (88, 166, 255)
YELLOW = (210, 153, 34)
WHITE = (230, 237, 243)

FONT_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "DejaVuSansMono.ttf",
    "CascadiaMono.ttf",
    "Consolas.ttf",
]

_TIMING = re.compile(r"\[[\d.]+ ms\]")
_CORPUS = re.compile(r"^(\s*corpus\s+)\S+")
_CITE = re.compile(r"^(\s*\[\d+\] )(.+?)(\s+\(bm25 [\d.]+\))$")


def font() -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default()


def capture() -> list[str]:
    """Run the demo exactly as a new user would and return its lines."""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    with tempfile.TemporaryDirectory() as td:
        out = subprocess.run(
            [sys.executable, "-m", "loci.cli", "demo", "--no-input", "--dir", td],
            capture_output=True, text=True, env=env, cwd=str(ROOT))
    if out.returncode != 0:
        raise SystemExit(out.stderr or "demo failed")
    lines = [_TIMING.sub("[0.1 ms]", ln).rstrip() for ln in out.stdout.splitlines()]
    # the card is a README illustration, so the scratch directory a CI or a
    # maintainer happens to use is shown as the documented default
    lines = [_CORPUS.sub(r"\1./loci-demo-notes", ln) for ln in lines]
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def wrap(lines: list[str], fnt: ImageFont.FreeTypeFont) -> list[str]:
    """Hard-wrap over-long lines at MAX_CHARS with a continuation indent."""
    out: list[str] = []
    for ln in lines:
        if len(ln) <= MAX_CHARS:
            out.append(ln)
            continue
        indent = " " * (len(ln) - len(ln.lstrip()) + 4)
        rest = ln
        while len(rest) > MAX_CHARS:
            cut = rest.rfind(" ", 0, MAX_CHARS)
            cut = cut if cut > MAX_CHARS // 2 else MAX_CHARS
            out.append(rest[:cut])
            rest = indent + rest[cut:].lstrip()
        out.append(rest)
    return out


def colorize(line: str) -> list[tuple[str, tuple[int, int, int]]]:
    """Split one line into (text, colour) runs."""
    if line.startswith("loci demo"):
        return [(line, WHITE)]
    if line.startswith("-- example"):
        return [(line, YELLOW)]
    if line.startswith("Next steps"):
        return [(line, WHITE)]
    m = _CITE.match(line)
    if m:
        return [(m.group(1), GREEN), (m.group(2), TEXT), (m.group(3), DIM)]
    stripped = line.strip()
    if line.startswith("            ") or line.startswith("        "):
        return [(line, DIM)]          # wrapped previews and hints
    if stripped.startswith(("corpus", "retrieval")) or \
            stripped.startswith(("fuses", "Add [embed]")):
        head, _, tail = line.partition("  ")
        return [(head + "  ", DIM), (tail, TEXT)]
    if line.startswith("  loci ") or line.startswith("  https://"):
        return [(line, BLUE)]
    return [(line, TEXT)]


def main() -> None:
    fnt = font()
    lines = wrap(capture(), fnt)

    text_w = max(fnt.getlength(ln) for ln in lines)
    width = max(int(text_w + 3 * PAD), MIN_WIDTH * SCALE)
    height = HEADER_H + PAD + len(lines) * LINE_H + PAD

    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, width - 1, height - 1], radius=12 * SCALE,
                        fill=CARD, outline=BORDER, width=SCALE)

    # title bar with the three window buttons
    d.line([0, HEADER_H, width, HEADER_H], fill=BORDER, width=1 * SCALE)
    for i, colour in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        cx = PAD // 2 + i * 20 * SCALE
        cy = HEADER_H // 2
        r = 5 * SCALE
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)
    label = "loci demo — no config, no key, no network"
    lw = fnt.getlength(label)
    d.text(((width - lw) / 2, (HEADER_H - fnt.size) / 2 - 2 * SCALE),
           label, font=fnt, fill=TITLE)

    y = HEADER_H + PAD // 2
    x0 = PAD
    for ln in lines:
        x = x0
        for text, colour in colorize(ln):
            d.text((x, y), text, font=fnt, fill=colour)
            x += fnt.getlength(text)
        y += LINE_H

    img = img.resize((width // SCALE, height // SCALE), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, optimize=True)
    print(f"wrote {OUT.relative_to(ROOT)} ({img.width}x{img.height})")


if __name__ == "__main__":
    main()
