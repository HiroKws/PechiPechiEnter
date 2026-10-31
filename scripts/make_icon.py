"""Build the enter-router icons (multi-size .ico per tray state) — drawn, not generated.

Why drawn (v2-u): the tray shows a 16 px icon, and a picture-model output cannot
survive that. Measured on a generated 1024 px source: the elbow closed up and the
stroke became a blurry 1-2 px hook, while the same shape drawn on the icon's own
pixel grid stayed readable. Drawing also keeps the icon reproducible from source
(no opaque binary to maintain) and lets every state be re-tinted from one design.

Geometry (one design, scaled by size, snapped to whole pixels):

    +-----+          bar  : bottom edge of the glyph box, from the arrow neck right
    |     |          stem : right edge of the glyph box, from the bar up
    |   +-+
    <---+            head : filled triangle pointing left, on the bar's centre line

    python scripts/make_icon.py                       # rebuild the .ico files
    python scripts/make_icon.py --preview p.png       # + a state x size sheet

Outputs (committed):
    src/enter_router/assets/enter-router.ico  app icon (green, 16..256)
    src/enter_router/assets/tray-<state>.ico  tray icon per state (16..64)
"""
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:                                     # pragma: no cover
    raise SystemExit("Pillow is required: python -m pip install pillow")

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "src" / "enter_router" / "assets"

#: (state, RGB) — the tray's own colours, converted from COLORREF 0x00BBGGRR.
STATE_RGB: dict[str, tuple[int, int, int]] = {
    "running": (0x22, 0xC5, 0x2E),     # 0x2EC522
    "paused": (0xFA, 0xCC, 0x15),      # 0x15CCFA
    "panic": (0xDC, 0x26, 0x26),       # 0x2626DC
    "busy": (0x3B, 0x82, 0xF6),        # 0xF6823B
}

APP_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
TRAY_SIZES = (16, 20, 24, 32, 40, 48, 64)
RADIUS_RATIO = 0.22          # squircle radius / size
GLYPH_RATIO = 0.70           # glyph box / size


def stroke_width(size: int) -> int:
    """Thick relative to the canvas when small, slimmer when large (optical)."""
    if size <= 16:
        return 2                                  # 3 px of 16 swallowed the elbow gap
    ratio = 0.17 if size <= 32 else (0.13 if size <= 96 else 0.105)
    return max(2, round(size * ratio))


def rounded_square(size: int, rgb: tuple[int, int, int]) -> Image.Image:
    """Full-bleed rounded square: corners transparent, everything else solid."""
    scale = 4                                     # supersample, clean corners
    big = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, size * scale - 1, size * scale - 1),
        radius=int(size * scale * RADIUS_RATIO), fill=rgb + (255,))
    return big.resize((size, size), Image.LANCZOS)


def draw_glyph(mask: Image.Image, size: int) -> None:
    """The return arrow, drawn on the icon's own pixel grid (no downscaling).

    The glyph box is 70% of the canvas so a 16 px icon still has a full pixel of
    background on every side, and the shape is nudged UP one pixel below 24 px —
    the stem's mass sits at the bottom, so the geometric centre looks low.
    """
    d = ImageDraw.Draw(mask)
    t = stroke_width(size)
    g = max(6, round(size * GLYPH_RATIO))
    ox = (size - g) // 2
    oy = (size - g) // 2                       # measured: no optical lift needed
    oy = max(0, min(oy, size - g))
    x0, x1 = ox, ox + g - 1
    y0, y1 = oy, oy + g - 1
    # bar along the bottom of the box, stem up the right edge
    d.rectangle((x0 + t, y1 - t + 1, x1, y1), fill=255)
    d.rectangle((x1 - t + 1, y0, x1, y1), fill=255)
    # arrowhead: filled triangle pointing left, centred on the bar
    mid = y1 - (t - 1) / 2
    d.polygon([(x0, mid),
               (x0 + t + 1, mid - t),
               (x0 + t + 1, mid + t)], fill=255)


def compose(size: int, rgb: tuple[int, int, int]) -> Image.Image:
    """One icon: flat state-coloured square + the white glyph."""
    icon = rounded_square(size, rgb)
    mask = Image.new("L", (size, size), 0)
    draw_glyph(mask, size)
    white = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    icon.paste(white, (0, 0), mask)
    return icon


def save_ico(path: Path, rgb: tuple[int, int, int], sizes: tuple[int, ...]) -> None:
    frames = [compose(size, rgb) for size in sizes]
    frames[-1].save(path, format="ICO",
                    sizes=[(f.width, f.height) for f in frames],
                    append_images=frames[:-1])
    print(f"wrote {path.relative_to(REPO)} sizes={sizes}")


def save_preview(path: Path) -> None:
    """One row per state: 256 (halved), then 48/32/24/16 upscaled 4x."""
    states = list(STATE_RGB)
    sizes = (256, 48, 32, 24, 16)
    widths = [128, 200, 140, 110, 80]
    pad, label = 14, 20
    width = sum(widths) + pad * (len(widths) + 1) + 100
    row_h = 148 + label
    sheet = Image.new("RGB", (width, row_h * len(states) + pad), (250, 250, 250))
    d = ImageDraw.Draw(sheet)
    for row, state in enumerate(states):
        y = pad + row * row_h
        x = pad
        for size, col_w in zip(sizes, widths):
            icon = compose(size, STATE_RGB[state])
            icon = (icon.resize((icon.width // 2, icon.height // 2), Image.LANCZOS)
                    if size > 48 else icon.resize((size * 4, size * 4), Image.NEAREST))
            sheet.paste(icon, (x, y), icon)
            d.text((x, y + icon.height + 3), f"{size}px", fill=(40, 40, 40))
            x += col_w + pad
        d.text((width - 90, y + 4), state, fill=(0, 0, 0))
    sheet.save(path)
    print(f"wrote preview {path}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preview", type=Path, default=None,
                    help="also write a PNG preview sheet (state x size)")
    args = ap.parse_args(argv)
    ASSETS.mkdir(parents=True, exist_ok=True)

    save_ico(ASSETS / "enter-router.ico", STATE_RGB["running"], APP_SIZES)
    for state, rgb in STATE_RGB.items():
        save_ico(ASSETS / f"tray-{state}.ico", rgb, TRAY_SIZES)
    if args.preview is not None:
        save_preview(args.preview)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
