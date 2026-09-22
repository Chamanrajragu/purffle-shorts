"""Everything drawn on top of the footage: word-synced animated captions, the hook title, the
watermark and the end call-to-action.

Two renderers produce the same look:
  * Pillow (default) — captions are pre-rendered PNG states played back by ffmpeg's concat demuxer
    as a single transparent overlay stream (active-word highlight, pop-in, glow, boxes).
  * libass — used for scripts that need complex text shaping (Hindi, Tamil, Arabic, Thai, ...)
    when Pillow was built without raqm, or when CAPTION_RENDERER=ass.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

from . import ffmpeg
from .config import Settings
from .timing import NO_SPACE_LANGS, Chunk
from .utils import download

log = logging.getLogger("purffle")

# ------------------------------------------------------------------------------------------ fonts
_GF = "https://github.com/google/fonts/raw/main/ofl/"
FONT_SOURCES = {
    "anton": ("Anton-Regular.ttf", _GF + "anton/Anton-Regular.ttf", "Anton"),
    "sans": ("NotoSans-Variable.ttf", _GF + "notosans/NotoSans%5Bwdth,wght%5D.ttf", "Noto Sans"),
    "deva": ("NotoSansDevanagari-Variable.ttf", _GF + "notosansdevanagari/NotoSansDevanagari%5Bwdth,wght%5D.ttf",
             "Noto Sans Devanagari"),
    "taml": ("NotoSansTamil-Variable.ttf", _GF + "notosanstamil/NotoSansTamil%5Bwdth,wght%5D.ttf", "Noto Sans Tamil"),
    "telu": ("NotoSansTelugu-Variable.ttf", _GF + "notosanstelugu/NotoSansTelugu%5Bwdth,wght%5D.ttf",
             "Noto Sans Telugu"),
    "beng": ("NotoSansBengali-Variable.ttf", _GF + "notosansbengali/NotoSansBengali%5Bwdth,wght%5D.ttf",
             "Noto Sans Bengali"),
    "arab": ("NotoSansArabic-Variable.ttf", _GF + "notosansarabic/NotoSansArabic%5Bwdth,wght%5D.ttf",
             "Noto Sans Arabic"),
    "thai": ("NotoSansThai-Variable.ttf", _GF + "notosansthai/NotoSansThai%5Bwdth,wght%5D.ttf", "Noto Sans Thai"),
    "jpan": ("NotoSansJP-Variable.ttf", _GF + "notosansjp/NotoSansJP%5Bwght%5D.ttf", "Noto Sans JP"),
    "kore": ("NotoSansKR-Variable.ttf", _GF + "notosanskr/NotoSansKR%5Bwght%5D.ttf", "Noto Sans KR"),
    "hans": ("NotoSansSC-Variable.ttf", _GF + "notosanssc/NotoSansSC%5Bwght%5D.ttf", "Noto Sans SC"),
}
LANG_FONT = {"hi": "deva", "mr": "deva", "ta": "taml", "te": "telu", "bn": "beng", "ar": "arab", "ur": "arab",
             "th": "thai", "ja": "jpan", "ko": "kore", "zh": "hans", "ru": "sans", "uk": "sans"}
COMPLEX_LANGS = {"hi", "mr", "ta", "te", "bn", "ar", "ur", "th"}
SYSTEM_BOLD = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]


def font_key(language: str, style_font: str) -> str:
    lang = language.split("-")[0]
    return LANG_FONT.get(lang, style_font)


def ensure_font(key: str, data_dir: Path) -> Path | None:
    """Download an open-licence Google Font once into data/fonts (falls back to system fonts)."""
    fname, url, _ = FONT_SOURCES[key]
    dest = data_dir / "fonts" / fname
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest
    try:
        download(url, dest, timeout=60, max_bytes=40 * 1024 * 1024)
        return dest
    except Exception as e:
        log.warning("Could not download font %s (%s); using a system font", fname, e)
        return None


def resolve_font(settings: Settings, style_font: str = "anton") -> tuple[Path | None, str]:
    """Return (font file, family name). CAPTION_FONT always wins."""
    if settings.caption_font and Path(settings.caption_font).exists():
        return Path(settings.caption_font), Path(settings.caption_font).stem
    key = font_key(settings.language, style_font)
    path = ensure_font(key, settings.data_path)
    if path:
        return path, FONT_SOURCES[key][2]
    for cand in SYSTEM_BOLD:
        if Path(cand).exists():
            return Path(cand), Path(cand).stem
    return None, "Arial"


@functools.lru_cache(maxsize=64)
def load_font(path: str | None, size: int, weight: int = 800) -> ImageFont.FreeTypeFont:
    size = max(8, int(size))
    if not path:
        return ImageFont.load_default(size=size)
    font = ImageFont.truetype(path, size)
    try:
        axes = font.get_variation_axes()
    except Exception:
        return font  # static font
    values = []
    for ax in axes:
        name = ax.get("name", b"")
        name = name.decode(errors="ignore") if isinstance(name, bytes) else str(name)
        if "eight" in name:  # Weight
            values.append(max(ax["minimum"], min(ax["maximum"], weight)))
        else:
            values.append(ax.get("default", ax["maximum"]))
    try:
        font.set_variation_by_axes(values)
    except Exception:
        pass
    return font


def needs_ass(settings: Settings) -> bool:
    mode = os.getenv("CAPTION_RENDERER", "auto").lower()
    if mode == "ass":
        return True
    if mode == "pillow":
        return False
    return settings.language.split("-")[0] in COMPLEX_LANGS and not features.check("raqm")


# ------------------------------------------------------------------------------------------ styles
@dataclass(frozen=True)
class CapStyle:
    fill: str = "#FFFFFF"
    active: str | None = "#FFE11A"
    spoken: str | None = None
    stroke: str = "#000000"
    stroke_ratio: float = 0.10
    shadow: bool = True
    box: str | None = None
    glow: str | None = None
    active_scale: float = 1.12
    pop: bool = True
    font: str = "anton"


CAPTION_STYLES = {
    "bold": CapStyle(),
    "boxed": CapStyle(active="#FFFFFF", box="#7C3AED", active_scale=1.0, stroke_ratio=0.07),
    "neon": CapStyle(active="#39FF14", glow="#00E5FF", stroke="#001018", stroke_ratio=0.05, shadow=False),
    "clean": CapStyle(active="#FFFFFF", active_scale=1.06, stroke_ratio=0.0, font="sans"),
    "karaoke": CapStyle(active="#FFE11A", spoken="#FFE11A", active_scale=1.06),
    "minimal": CapStyle(active=None, active_scale=1.0, pop=False),
}
POP_SCALES = (0.78, 1.07)
CENTER_Y = {"upper": 0.30, "center": 0.56, "lower": 0.68}


def _rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha


def display_word(text: str, uppercase: bool) -> str:
    t = text.strip().strip(",.;:\"“”()[]")
    t = t or text.strip()
    return t.upper() if uppercase else t


# ------------------------------------------------------------------------------------------ Pillow captions
class PillowCaptions:
    def __init__(self, settings: Settings, style: CapStyle, font_path: Path | None):
        self.s, self.style = settings, style
        self.font_path = str(font_path) if font_path else None
        self.W, self.H = settings.resolution
        self.band_h = int(self.H * 0.30) // 2 * 2
        cy = CENTER_Y.get(settings.caption_position, CENTER_Y["center"])
        self.band_y = int(self.H * cy - self.band_h / 2)
        default = 0.098 if style.font == "anton" else 0.078
        self.base = settings.caption_fontsize or int(self.W * default)
        self.max_w = int(self.W * 0.84)
        self.joiner = "" if settings.language.split("-")[0] in NO_SPACE_LANGS else " "

    def _layout(self, words: list[str], size: int):
        font = load_font(self.font_path, size)
        sw = int(round(size * self.style.stroke_ratio))
        space = font.getlength(self.joiner) if self.joiner else 0
        if space:  # leave room for the enlarged active word so it never collides with its neighbours
            space += max(0.0, (self.style.active_scale - 1.0) * 1.6 * size - sw)
        widths = [font.getlength(w) + sw for w in words]
        lines, cur, cur_w = [], [], 0.0
        for i, w in enumerate(widths):
            add = w + (space if cur else 0)
            if cur and cur_w + add > self.max_w:
                lines.append((cur, cur_w))
                cur, cur_w = [], 0.0
                add = w
            cur.append(i)
            cur_w += add
        if cur:
            lines.append((cur, cur_w))
        return font, sw, space, widths, lines

    def fit_size(self, words: list[str]) -> int:
        size = self.base
        for _ in range(8):
            _, sw, _, widths, lines = self._layout(words, size)
            if len(lines) <= 2 and max(widths) <= self.max_w:
                break
            size = int(size * 0.9)
        return size

    def render(self, words: list[str], active: int | None, size: int, scale: float = 1.0) -> Image.Image:
        st = self.style
        size = max(10, int(size * scale))
        font, sw, space, widths, lines = self._layout(words, size)
        ascent, descent = font.getmetrics()
        line_h = ascent + descent + sw
        gap = int(size * 0.08)
        total_h = len(lines) * line_h + (len(lines) - 1) * gap
        y = (self.band_h - total_h) / 2

        img = Image.new("RGBA", (self.W, self.band_h), (0, 0, 0, 0))
        fx = Image.new("RGBA", img.size, (0, 0, 0, 0)) if (st.shadow or st.glow) else None
        draw, fxd = ImageDraw.Draw(img), ImageDraw.Draw(fx) if fx else None
        big = load_font(self.font_path, int(size * st.active_scale)) if st.active_scale != 1.0 else font
        big_sw = int(round(big.size * st.stroke_ratio))

        for idxs, line_w in lines:
            x = (self.W - line_w) / 2
            baseline = y + sw + ascent
            for i in idxs:
                word, w = words[i], widths[i]
                is_active = active is not None and i == active
                f, s_w = (big, big_sw) if is_active else (font, sw)
                if is_active and st.box:
                    s_w = 0  # a boxed word reads cleaner without an outline
                wx = x + (w - f.getlength(word)) / 2 if is_active else x + sw / 2
                color = st.fill
                if is_active and st.active:
                    color = st.active
                elif st.spoken and active is not None and i < active:
                    color = st.spoken
                if is_active and st.box:
                    pad_x, pad_y = size * 0.16, size * 0.12
                    x0, y0, x1, y1 = draw.textbbox((wx, baseline), word, font=f, anchor="ls")
                    draw.rounded_rectangle((x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y),
                                           radius=int(size * 0.2), fill=_rgba(st.box))
                if fxd is not None and not (is_active and st.box):
                    if st.glow:
                        fxd.text((wx, baseline), word, font=f, anchor="ls", fill=_rgba(st.glow),
                                 stroke_width=max(2, s_w * 3), stroke_fill=_rgba(st.glow))
                    else:
                        off = max(2, int(size * 0.05))
                        fxd.text((wx + off, baseline + off), word, font=f, anchor="ls", fill=(0, 0, 0, 170),
                                 stroke_width=s_w, stroke_fill=(0, 0, 0, 170))
                draw.text((wx, baseline), word, font=f, anchor="ls", fill=_rgba(color),
                          stroke_width=s_w, stroke_fill=_rgba(st.stroke))
                x += w + space
            y += line_h + gap

        if fx is not None:
            fx = fx.filter(ImageFilter.GaussianBlur(radius=size * (0.12 if st.glow else 0.05)))
            if st.glow:
                fx = Image.alpha_composite(fx, fx)
            img = Image.alpha_composite(fx, img)
        return img

    def build(self, chunks: list[Chunk], total: float, out_dir: Path) -> Path:
        """Render every caption state and write an ffconcat playlist spanning ``total`` seconds."""
        out_dir.mkdir(parents=True, exist_ok=True)
        fps = self.s.fps
        frame = 1.0 / fps
        blank = out_dir / "blank.png"
        Image.new("RGBA", (self.W, self.band_h), (0, 0, 0, 0)).save(blank)
        entries: list[tuple[str, float]] = []
        t = 0.0
        n = 0

        def add(name: str, until: float):
            nonlocal t
            if until - t > 0.001:
                entries.append((name, until - t))
                t = until

        for ci, chunk in enumerate(chunks):
            words = [display_word(w.text, self.s.caption_uppercase) for w in chunk.words]
            if not any(words):
                continue
            size = self.fit_size(words)
            add(blank.name, chunk.start)
            states = range(len(words)) if self.style.active or self.style.spoken else [None]
            for k in states:
                if k is None:
                    end = chunk.end
                else:
                    end = chunk.words[k + 1].start if k + 1 < len(words) else chunk.end
                    end = min(max(end, t), chunk.end)
                if k in (0, None) and self.style.pop:
                    for sc in POP_SCALES:
                        n += 1
                        name = f"c{ci:04d}_pop{n:05d}.png"
                        self.render(words, k, size, sc).save(out_dir / name, compress_level=1)
                        add(name, min(t + frame, end))
                n += 1
                name = f"c{ci:04d}_w{n:05d}.png"
                self.render(words, k, size).save(out_dir / name, compress_level=1)
                add(name, end)
        add(blank.name, total)
        if not entries:
            entries.append((blank.name, total))
        lines = ["ffconcat version 1.0"]
        for name, dur in entries:
            lines += [f"file '{name}'", f"duration {dur:.4f}"]
        lines.append(f"file '{entries[-1][0]}'")  # concat demuxer quirk: repeat the last file
        playlist = out_dir / "captions.ffconcat"
        playlist.write_text("\n".join(lines) + "\n")
        log.info("Captions: %d states rendered (%s style)", n, self.s.caption_style)
        return playlist


# ------------------------------------------------------------------------------------------ static PNG overlays
def _text_box(settings: Settings, font_path: Path | None, text: str, *, size_ratio: float, fill: str,
              box: str | None, box_alpha: int, max_lines: int = 3, uppercase: bool = True) -> Image.Image:
    W = settings.width
    text = text.upper() if uppercase else text
    size = int(W * size_ratio)
    max_w = int(W * 0.80)
    for _ in range(10):
        font = load_font(str(font_path) if font_path else None, size)
        words, lines, cur = text.split(), [], ""
        for w in words:
            cand = f"{cur} {w}".strip()
            if font.getlength(cand) <= max_w or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines and all(font.getlength(line) <= max_w for line in lines):
            break
        size = int(size * 0.9)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    pad = int(size * 0.45)
    sw = max(1, int(size * 0.06)) if not box else 0
    tw = int(max(font.getlength(line) for line in lines)) + 2 * pad + 2 * sw
    th = line_h * len(lines) + 2 * pad
    img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if box:
        d.rounded_rectangle((0, 0, tw - 1, th - 1), radius=int(size * 0.35), fill=_rgba(box, box_alpha))
    y = pad
    for line in lines:
        d.text((tw / 2, y + ascent), line, font=font, anchor="ms", fill=_rgba(fill),
               stroke_width=sw, stroke_fill=(0, 0, 0, 255))
        y += line_h
    return img


def hook_png(settings: Settings, font_path: Path | None, text: str, dest: Path) -> tuple[Path, int]:
    img = _text_box(settings, font_path, text, size_ratio=0.075, fill="#FFFFFF", box="#000000", box_alpha=175)
    img.save(dest)
    return dest, int(settings.height * 0.15)


def cta_png(settings: Settings, font_path: Path | None, text: str, dest: Path) -> tuple[Path, int]:
    img = _text_box(settings, font_path, text, size_ratio=0.062, fill="#FFFFFF", box="#FF0033", box_alpha=235,
                    max_lines=2)
    img.save(dest)
    return dest, int(settings.height * 0.30)


def watermark_png(settings: Settings, font_path: Path | None, text: str, dest: Path) -> tuple[Path, int]:
    font = load_font(str(font_path) if font_path else None, int(settings.width * 0.034))
    sw = 2
    w = int(font.getlength(text)) + 8 + 2 * sw
    ascent, descent = font.getmetrics()
    img = Image.new("RGBA", (w, ascent + descent + 8), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((4 + sw, 4 + ascent), text, font=font, anchor="ls", fill=(255, 255, 255, 150),
                             stroke_width=sw, stroke_fill=(0, 0, 0, 110))
    img.save(dest)
    return dest, int(settings.height * 0.045)


# ------------------------------------------------------------------------------------------ libass
def _ass_color(hex_color: str, alpha: int = 0) -> str:
    r, g, b, _ = _rgba(hex_color)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(t: str) -> str:
    return t.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def write_ass(settings: Settings, style: CapStyle, family: str, chunks: list[Chunk], total: float, dest: Path, *,
              hook: str = "", hook_until: float = 0.0, cta: str = "", cta_from: float = 0.0,
              watermark: str = "") -> Path:
    W, H = settings.resolution
    size = settings.caption_fontsize or int(W * 0.085)
    outline = max(2, int(size * (style.stroke_ratio or 0.06)))
    cy = int(H * CENTER_Y.get(settings.caption_position, CENTER_Y["center"]))
    joiner = "" if settings.language.split("-")[0] in NO_SPACE_LANGS else " "
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "ScaledBorderAndShadow: yes", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Cap,{family},{size},{_ass_color(style.fill)},{_ass_color(style.active or style.fill)},"
        f"{_ass_color(style.glow or style.stroke)},&H96000000,-1,0,0,0,100,100,0,0,1,{outline},"
        f"{2 if style.shadow else 0},5,40,40,0,1",
        f"Style: Hook,{family},{int(W * 0.07)},&H00FFFFFF,&H00FFFFFF,&H50000000,&H50000000,-1,0,0,0,100,100,0,0,3,"
        f"{int(W * 0.02)},0,8,60,60,{int(H * 0.15)},1",
        f"Style: Cta,{family},{int(W * 0.058)},&H00FFFFFF,&H00FFFFFF,&H003300FF,&H003300FF,-1,0,0,0,100,100,0,0,3,"
        f"{int(W * 0.022)},0,8,60,60,{int(H * 0.30)},1",
        f"Style: Mark,{family},{int(W * 0.032)},&H66FFFFFF,&H66FFFFFF,&H90000000,&H00000000,-1,0,0,0,100,100,0,0,1,"
        f"2,0,8,20,20,{int(H * 0.045)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    active_c = _ass_color(style.active) if style.active else None
    big = int(style.active_scale * 100)
    for chunk in chunks:
        words = [_ass_escape(display_word(w.text, settings.caption_uppercase)) for w in chunk.words]
        states = range(len(words)) if (style.active or style.spoken) else [None]
        for k in states:
            start = chunk.start if k in (0, None) else chunk.words[k].start
            end = chunk.end if k is None or k + 1 >= len(words) else chunk.words[k + 1].start
            if end - start < 0.01:
                continue
            parts = []
            for i, w in enumerate(words):
                if k is not None and i == k and active_c:
                    parts.append(f"{{\\c{active_c}\\fscx{big}\\fscy{big}}}{w}{{\\r}}")
                elif style.spoken and k is not None and i < k:
                    parts.append(f"{{\\c{_ass_color(style.spoken)}}}{w}{{\\r}}")
                else:
                    parts.append(w)
            pop = ("{\\fscx78\\fscy78\\t(0,70,\\fscx107\\fscy107)\\t(70,130,\\fscx100\\fscy100)}"
                   if style.pop and k in (0, None) else "")
            blur = "{\\blur6}" if style.glow else ""
            lines.append(f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,"
                         f"{{\\pos({W // 2},{cy})}}{blur}{pop}{joiner.join(parts)}")
    if hook:
        lines.append(f"Dialogue: 2,{_ass_time(0)},{_ass_time(hook_until)},Hook,,0,0,0,,{{\\fad(150,300)}}"
                     f"{_ass_escape(hook.upper())}")
    if cta:
        lines.append(f"Dialogue: 2,{_ass_time(cta_from)},{_ass_time(total)},Cta,,0,0,0,,{{\\fad(250,0)}}"
                     f"{_ass_escape(cta)}")
    if watermark:
        lines.append(f"Dialogue: 0,{_ass_time(0)},{_ass_time(total)},Mark,,0,0,0,,{_ass_escape(watermark)}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


# ------------------------------------------------------------------------------------------ plan
@dataclass
class OverlayPlan:
    mode: str                                  # pillow | ass
    captions: Path | None = None               # ffconcat playlist (pillow)
    captions_y: int = 0
    hook: tuple[Path, int] | None = None       # (png, y)
    hook_until: float = 0.0
    watermark: tuple[Path, int] | None = None
    cta: tuple[Path, int] | None = None
    cta_from: float = 0.0
    ass: Path | None = None                    # subtitles file (ass)
    fonts_dir: Path | None = None


def build_overlays(settings: Settings, chunks: list[Chunk], total: float, hook_text: str, work: Path) -> OverlayPlan:
    style = CAPTION_STYLES.get(settings.caption_style, CAPTION_STYLES["bold"])
    if not settings.caption_uppercase and style.font == "anton":
        style = replace(style, font="sans")
    font_path, family = resolve_font(settings, style.font)
    hook_until = min(2.8, total * 0.4) if settings.hook_overlay and hook_text else 0.0
    cta_text = settings.end_cta.strip()
    cta_from = max(total - 2.6, total * 0.6) if cta_text else 0.0

    if needs_ass(settings) and ffmpeg.has_filter("ass"):
        fonts = work / "fonts"
        fonts.mkdir(parents=True, exist_ok=True)
        if font_path:
            shutil.copy(font_path, fonts / font_path.name)
        ass = write_ass(settings, style, family, chunks, total, work / "captions.ass",
                        hook=hook_text if hook_until else "", hook_until=hook_until,
                        cta=cta_text, cta_from=cta_from, watermark=settings.watermark_text)
        log.info("Captions: libass renderer (%s, font %s)", settings.language, family)
        return OverlayPlan("ass", ass=ass, fonts_dir=fonts)

    caps = PillowCaptions(settings, style, font_path)
    plan = OverlayPlan("pillow", captions=caps.build(chunks, total, work / "captions"), captions_y=caps.band_y)
    ui_font, _ = resolve_font(settings, "anton" if settings.caption_uppercase else "sans")
    if hook_until:
        plan.hook, plan.hook_until = hook_png(settings, ui_font, hook_text, work / "hook.png"), hook_until
    if settings.watermark_text:
        plan.watermark = watermark_png(settings, ui_font, settings.watermark_text, work / "watermark.png")
    if cta_text:
        plan.cta, plan.cta_from = cta_png(settings, ui_font, cta_text, work / "cta.png"), cta_from
    return plan
