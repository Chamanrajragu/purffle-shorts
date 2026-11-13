"""Make the desktop app icons from the logo (purffle_shorts/web/icon.svg), with Pillow only.

    python packaging/make_icons.py

Writes packaging/icon.png (1024 px, Linux and the website), packaging/icon.ico (Windows),
packaging/icon.icns (macOS) and purffle_shorts/web/icon.png (192 px, for the Studio's notifications).
The logo is three flat shapes on a 48-unit grid, drawn here at 4x and scaled down for clean edges.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
INK, PAPER, TALLY = "#15130F", "#F2EEE5", "#E5432A"


def draw(size: int = 1024) -> Image.Image:
    big = size * 4
    u = big / 48                                    # one unit of the 48 x 48 logo grid
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, big - 1, big - 1), radius=round(10 * u), fill=INK)
    # the film strip: a bar with rounded left corners
    d.rounded_rectangle((13 * u, 9.5 * u, 20.5 * u, 38.5 * u), radius=round(1.5 * u), fill=PAPER)
    d.rectangle((17 * u, 9.5 * u, 20.5 * u, 38.5 * u), fill=PAPER)
    # the play triangle, with the logo's rounded 1.2-unit stroke
    tri = [(20.5 * u, 9.5 * u), (37 * u, 19.25 * u), (20.5 * u, 29 * u)]
    d.polygon(tri, fill=TALLY)
    d.line([*tri, tri[0]], fill=TALLY, width=round(1.2 * u), joint="curve")
    r = 0.6 * u
    for x, y in tri:
        d.ellipse((x - r, y - r, x + r, y + r), fill=TALLY)
    return im.resize((size, size), Image.LANCZOS)


def main() -> None:
    icon = draw(1024)
    out = ROOT / "packaging"
    icon.save(out / "icon.png")
    icon.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(out / "icon.icns")
    draw(192).save(ROOT / "purffle_shorts" / "web" / "icon.png", optimize=True)
    print("Icons written to", out)


if __name__ == "__main__":
    main()
