"""Everything drawn on top of the footage: word-synced animated captions, the hook title, the
watermark, the end call-to-action, for chat stories an animated text-message screen, and for
Reddit-style stories the post card shown while the title is read.

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
# Dialogue: speaker B's highlight and name tag use a second colour so viewers can tell who is talking.
SPEAKER_B = {"active": "#4FC3F7", "box": "#0EA5E9", "tag": "#4FC3F7"}
SPEAKER_A_TAG = "#FFE11A"
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
    def __init__(self, settings: Settings, style: CapStyle, font_path: Path | None,
                 labels: dict[str, str] | None = None):
        self.s, self.style = settings, style
        self.font_path = str(font_path) if font_path else None
        self.W, self.H = settings.resolution
        self.band_h = int(self.H * 0.30) // 2 * 2
        cy = CENTER_Y.get(settings.caption_position, CENTER_Y["center"])
        self.band_y = int(self.H * cy - self.band_h / 2)
        default = 0.098 if style.font == "anton" else 0.078
        self.base = settings.caption_fontsize or int(settings.unit * default)
        self.max_w = int(self.W * 0.84)
        self.joiner = "" if settings.language.split("-")[0] in NO_SPACE_LANGS else " "
        self.labels = labels or {}   # speaker -> name tag (dialogue)
        self._styles = {"A": style, "B": replace(style, active=SPEAKER_B["active"] if style.active else None,
                                                 box=SPEAKER_B["box"] if style.box else None,
                                                 spoken=SPEAKER_B["active"] if style.spoken else None)}

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

    def render(self, words: list[str], active: int | None, size: int, scale: float = 1.0,
               speaker: str = "A") -> Image.Image:
        st = self._styles.get(speaker, self.style)
        size = max(10, int(size * scale))
        font, sw, space, widths, lines = self._layout(words, size)
        ascent, descent = font.getmetrics()
        line_h = ascent + descent + sw
        gap = int(size * 0.08)
        total_h = len(lines) * line_h + (len(lines) - 1) * gap
        y = (self.band_h - total_h) / 2

        img = Image.new("RGBA", (self.W, self.band_h), (0, 0, 0, 0))
        label = self.labels.get(speaker)
        if label:
            self._name_tag(img, label, SPEAKER_B["tag"] if speaker == "B" else SPEAKER_A_TAG, y)
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

    def _name_tag(self, img: Image.Image, text: str, color: str, text_top: float) -> None:
        size = int(self.s.unit * 0.04)
        font = load_font(self.font_path, size)
        pad_x, pad_y = int(size * 0.55), int(size * 0.28)
        tw = int(font.getlength(text))
        ascent, descent = font.getmetrics()
        h = ascent + descent + 2 * pad_y
        y1 = int(max(0, text_top - size * 0.35))
        y0 = max(0, y1 - h)
        x0 = (self.W - tw) // 2 - pad_x
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((x0, y0, x0 + tw + 2 * pad_x, y0 + h), radius=h // 2, fill=_rgba(color, 235))
        d.text((x0 + pad_x, y0 + pad_y + ascent), text, font=font, anchor="ls", fill=(10, 10, 14, 255))

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
                        self.render(words, k, size, sc, chunk.speaker).save(out_dir / name, compress_level=1)
                        add(name, min(t + frame, end))
                n += 1
                name = f"c{ci:04d}_w{n:05d}.png"
                self.render(words, k, size, speaker=chunk.speaker).save(out_dir / name, compress_level=1)
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
    text = text.upper() if uppercase else text
    size = int(settings.unit * size_ratio)
    max_w = int(min(settings.width * 0.80, settings.unit * 1.2))
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


def hook_png(settings: Settings, font_path: Path | None, text: str, dest: Path,
             y_ratio: float = 0.15, max_lines: int = 3) -> tuple[Path, int]:
    img = _text_box(settings, font_path, text, size_ratio=0.075, fill="#FFFFFF", box="#000000", box_alpha=175,
                    max_lines=max_lines)
    img.save(dest)
    return dest, int(settings.height * y_ratio)


def cta_png(settings: Settings, font_path: Path | None, text: str, dest: Path,
            y_ratio: float = 0.30) -> tuple[Path, int]:
    img = _text_box(settings, font_path, text, size_ratio=0.062, fill="#FFFFFF", box="#FF0033", box_alpha=235,
                    max_lines=2)
    img.save(dest)
    return dest, int(settings.height * y_ratio)


def watermark_png(settings: Settings, font_path: Path | None, text: str, dest: Path) -> tuple[Path, int]:
    font = load_font(str(font_path) if font_path else None, int(settings.unit * 0.034))
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
              watermark: str = "", hook_y: float = 0.15, cta_y: float = 0.30,
              labels: dict[str, str] | None = None) -> Path:
    W, H = settings.resolution
    U = settings.unit
    size = settings.caption_fontsize or int(U * 0.085)
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
        f"Style: Hook,{family},{int(U * 0.07)},&H00FFFFFF,&H00FFFFFF,&H50000000,&H50000000,-1,0,0,0,100,100,0,0,3,"
        f"{int(U * 0.02)},0,8,60,60,{int(H * hook_y)},1",
        f"Style: Cta,{family},{int(U * 0.058)},&H00FFFFFF,&H00FFFFFF,&H003300FF,&H003300FF,-1,0,0,0,100,100,0,0,3,"
        f"{int(U * 0.022)},0,8,60,60,{int(H * cta_y)},1",
        f"Style: Mark,{family},{int(U * 0.032)},&H66FFFFFF,&H66FFFFFF,&H90000000,&H00000000,-1,0,0,0,100,100,0,0,1,"
        f"2,0,8,20,20,{int(H * 0.045)},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    big = int(style.active_scale * 100)
    labels = labels or {}
    for chunk in chunks:
        b = chunk.speaker == "B"
        active_c = _ass_color(SPEAKER_B["active"] if b else style.active) if style.active else None
        spoken_c = _ass_color(SPEAKER_B["active"] if b else style.spoken) if style.spoken else None
        tag = labels.get(chunk.speaker)
        if tag:
            tag_c = _ass_color(SPEAKER_B["tag"] if b else SPEAKER_A_TAG)
            lines.append(f"Dialogue: 1,{_ass_time(chunk.start)},{_ass_time(chunk.end)},Cap,,0,0,0,,"
                         f"{{\\pos({W // 2},{int(cy - size * 1.3)})\\fs{int(U * 0.036)}\\c{tag_c}}}{_ass_escape(tag)}")
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
                elif spoken_c and k is not None and i < k:
                    parts.append(f"{{\\c{spoken_c}}}{w}{{\\r}}")
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


# ------------------------------------------------------------------------------------------ chat stories
@dataclass
class ChatMessage:
    speaker: str        # A = the contact (left), B = "Me" (right)
    text: str
    start: float


class ChatScreen:
    """A phone-style text conversation where each message pops in as it is read aloud, with a typing
    indicator before the contact's replies. Played back like the captions: PNG states + ffconcat."""

    def __init__(self, settings: Settings, font_path: Path | None, contact: str):
        self.s = settings
        W, H, U = settings.width, settings.height, settings.unit
        self.pw = int(min(W * 0.88, U * 0.92)) // 2 * 2
        self.x = (W - self.pw) // 2
        self.y = int(H * 0.25)
        self.ph = int(H * 0.66) // 2 * 2
        self.font_path = str(font_path) if font_path else None
        self.size = int(U * 0.043)
        self.font = load_font(self.font_path, self.size, weight=500)
        self.pad = int(U * 0.03)
        self.header_h = int(U * 0.13)
        self.contact = contact or "Unknown"
        self.max_bubble = int(self.pw * 0.74)
        self.line_h = sum(self.font.getmetrics()) + int(self.size * 0.12)
        self.gap = int(self.size * 0.45)

    def _wrap(self, text: str) -> list[str]:
        lines, cur = [], ""
        inner = self.max_bubble - 2 * int(self.size * 0.7)
        for w in text.split():
            cand = f"{cur} {w}".strip()
            if not cur or self.font.getlength(cand) <= inner:
                cur = cand
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines or [""]

    def _bubble_h(self, msg: ChatMessage | None) -> int:
        n = len(self._wrap(msg.text)) if msg else 1
        return n * self.line_h + int(self.size * 0.9)

    def _base(self) -> Image.Image:
        img = Image.new("RGBA", (self.pw, self.ph), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        r = int(self.s.unit * 0.05)
        d.rounded_rectangle((0, 0, self.pw - 1, self.ph - 1), radius=r, fill=(14, 15, 20, 238))
        d.rounded_rectangle((0, 0, self.pw - 1, self.header_h), radius=r, fill=(28, 29, 36, 255))
        d.rectangle((0, self.header_h - r, self.pw - 1, self.header_h), fill=(28, 29, 36, 255))
        # avatar with the contact's initial, then the name
        av = int(self.header_h * 0.58)
        ax, ay = self.pad, (self.header_h - av) // 2
        d.ellipse((ax, ay, ax + av, ay + av), fill=(99, 102, 241, 255))
        big = load_font(self.font_path, int(av * 0.5), weight=700)
        initial = (self.contact.strip()[:1] or "?").upper()
        d.text((ax + av / 2, ay + av / 2), initial, font=big, anchor="mm", fill=(255, 255, 255, 255))
        name_font = load_font(self.font_path, int(self.size * 1.05), weight=700)
        d.text((ax + av + self.pad * 0.8, self.header_h / 2), self.contact, font=name_font, anchor="lm",
               fill=(245, 246, 250, 255))
        d.line((0, self.header_h, self.pw, self.header_h), fill=(255, 255, 255, 28), width=2)
        return img

    def _draw_bubble(self, d: ImageDraw.ImageDraw, msg: ChatMessage | None, y: int, alpha: int = 255) -> None:
        pad_x, pad_y = int(self.size * 0.7), int(self.size * 0.45)
        mine = msg is not None and msg.speaker == "B"
        if msg is None:  # typing indicator
            w = int(self.size * 2.6)
            h = self._bubble_h(None)
            x0 = self.pad
            d.rounded_rectangle((x0, y, x0 + w, y + h), radius=int(self.size * 0.8), fill=(44, 44, 50, alpha))
            r = max(3, int(self.size * 0.14))
            for k in range(3):
                cx = x0 + w * (0.3 + 0.2 * k)
                d.ellipse((cx - r, y + h / 2 - r, cx + r, y + h / 2 + r), fill=(170, 170, 180, alpha))
            return
        lines = self._wrap(msg.text)
        tw = int(max(self.font.getlength(ln) for ln in lines))
        w, h = tw + 2 * pad_x, self._bubble_h(msg)
        x0 = self.pw - self.pad - w if mine else self.pad
        fill = (10, 132, 255, alpha) if mine else (44, 44, 50, alpha)
        d.rounded_rectangle((x0, y, x0 + w, y + h), radius=int(self.size * 0.8), fill=fill)
        ascent = self.font.getmetrics()[0]
        ty = y + pad_y
        for ln in lines:
            d.text((x0 + pad_x, ty + ascent), ln, font=self.font, anchor="ls", fill=(255, 255, 255, alpha))
            ty += self.line_h

    def render(self, shown: list[ChatMessage], typing: bool = False, enter: float = 0.0) -> Image.Image:
        """``enter`` (0..1) slides the newest bubble up into place."""
        img = self._base()
        d = ImageDraw.Draw(img)
        items: list[ChatMessage | None] = list(shown) + ([None] if typing else [])
        top, bottom = self.header_h + self.pad, self.ph - self.pad
        heights = [self._bubble_h(m) for m in items]
        # Newest messages stay visible: drop the oldest until the rest fit (the chat "scrolls").
        first = 0
        while first < len(items) - 1 and sum(heights[first:]) + self.gap * (len(items) - first - 1) > bottom - top:
            first += 1
        y = top
        for k in range(first, len(items)):
            newest = k == len(items) - 1
            dy = int(self.size * 0.8 * enter) if newest else 0
            alpha = int(255 * (1 - 0.5 * enter)) if newest else 255
            self._draw_bubble(d, items[k], y + dy, alpha)
            y += heights[k] + self.gap
        return img

    def build(self, messages: list[ChatMessage], total: float, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        frame = 1.0 / self.s.fps
        entries: list[tuple[str, float]] = []
        t, n = 0.0, 0

        def add(img: Image.Image, until: float):
            nonlocal t, n
            if until - t > 0.001:
                n += 1
                name = f"chat{n:04d}.png"
                img.save(out_dir / name, compress_level=1)
                entries.append((name, until - t))
                t = until

        for k, msg in enumerate(messages):
            shown = messages[:k]
            if k and msg.speaker == "A":  # the contact is typing...
                typing_from = max(t, msg.start - 0.55)
                add(self.render(shown), typing_from)
                add(self.render(shown, typing=True), msg.start)
            else:
                add(self.render(shown), msg.start)
            end = messages[k + 1].start if k + 1 < len(messages) else total
            for e in (0.6, 0.25):  # pop-in
                add(self.render(messages[:k + 1], enter=e), min(t + frame, end))
        add(self.render(messages), total)
        if not entries:
            add(self.render(messages), max(total, frame))
        lines = ["ffconcat version 1.0"]
        for name, dur in entries:
            lines += [f"file '{name}'", f"duration {dur:.4f}"]
        lines.append(f"file '{entries[-1][0]}'")
        playlist = out_dir / "chat.ffconcat"
        playlist.write_text("\n".join(lines) + "\n")
        log.info("Chat screen: %d messages, %d states", len(messages), n)
        return playlist


# ------------------------------------------------------------------------------------------ story post card
CARD_ACCENTS = ["#FF6B35", "#7C3AED", "#0EA5E9", "#10B981", "#F59E0B", "#EC4899"]


def _compact(n: int) -> str:
    return (f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k") if n >= 1000 else str(n)


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int, by_char: bool = False) -> list[str]:
    tokens = list(text) if by_char else text.split()
    sep = "" if by_char else " "
    lines, cur = [], ""
    for tok in tokens:
        cand = f"{cur}{sep}{tok}" if cur else tok
        if not cur or font.getlength(cand) <= width:
            cur = cand
        else:
            lines.append(cur)
            cur = tok.lstrip() if by_char else tok
    if cur:
        lines.append(cur)
    return lines or [""]


def post_card_png(settings: Settings, font_path: Path | None, community: str, user: str, title: str,
                  dest: Path) -> tuple[Path, int, int]:
    """A forum-post card (community, poster, title, votes, comments) shown while the title is read aloud,
    the way Reddit story videos open. The numbers are decoration, derived from the title so a re-render
    draws the same card. Returns (png, x, y)."""
    W, H, U = settings.width, settings.height, settings.unit
    cw = int(min(W * 0.88, U * 0.95)) // 2 * 2
    pad = int(U * 0.045)
    fp = str(font_path) if font_path else None
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(title))
    accent = _rgba(CARD_ACCENTS[seed % len(CARD_ACCENTS)])
    votes, comments = 1200 + seed * 37 % 46000, 90 + seed * 13 % 3800
    ink, grey, pill = (26, 26, 27, 255), (112, 117, 122, 255), (234, 237, 239, 255)
    by_char = settings.language.split("-")[0] in NO_SPACE_LANGS

    size = int(U * 0.058)
    for _ in range(12):
        title_f = load_font(fp, size, weight=700)
        lines = _wrap(title, title_f, cw - 2 * pad, by_char)
        if len(lines) <= 6:
            break
        size = int(size * 0.9)
    ascent, descent = title_f.getmetrics()
    line_h = ascent + descent + int(size * 0.08)
    name_f = load_font(fp, int(U * 0.036), weight=700)
    meta_f = load_font(fp, int(U * 0.03), weight=500)
    small_f = load_font(fp, int(U * 0.031), weight=700)

    av = int(U * 0.075)
    title_top = pad + av + int(pad * 0.55)
    foot_top = title_top + line_h * len(lines) + int(pad * 0.45)
    foot_h = int(U * 0.062)
    ch = foot_top + foot_h + pad
    img = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, cw - 1, ch - 1), radius=int(U * 0.035), fill=(255, 255, 255, 250),
                        outline=(0, 0, 0, 40), width=2)
    # header: avatar with the community's initial, community name, poster and age
    d.ellipse((pad, pad, pad + av, pad + av), fill=accent)
    core = community.split("/", 1)[-1]
    d.text((pad + av / 2, pad + av / 2), (core[:1] or "?").upper(),
           font=load_font(fp, int(av * 0.52), weight=800), anchor="mm", fill=(255, 255, 255, 255))
    tx = pad + av + int(pad * 0.45)
    d.text((tx, pad + av * 0.30), community, font=name_f, anchor="lm", fill=ink)
    d.text((tx, pad + av * 0.76), f"{user} · {3 + seed % 20}h", font=meta_f, anchor="lm", fill=grey)
    y = title_top
    for ln in lines:
        d.text((pad, y + ascent), ln, font=title_f, anchor="ls", fill=ink)
        y += line_h

    # footer pills: votes, comments, share
    x, r = pad, foot_h // 2
    mid = foot_top + foot_h / 2
    a = foot_h * 0.36                                              # arrow size

    def up(cx: float, cy: float, s: float, down: bool = False) -> None:
        k = -1 if down else 1
        d.polygon([(cx - s / 2, cy + k * s * 0.05), (cx, cy - k * s / 2), (cx + s / 2, cy + k * s * 0.05)], fill=ink)
        d.rectangle((cx - s * 0.17, min(cy, cy + k * s * 0.5), cx + s * 0.17, max(cy, cy + k * s * 0.5)), fill=ink)

    votes_txt = _compact(votes)
    w1 = int(a * 2 + small_f.getlength(votes_txt) + foot_h * 1.1)
    d.rounded_rectangle((x, foot_top, x + w1, foot_top + foot_h), radius=r, fill=pill)
    up(x + foot_h * 0.45, mid, a)
    d.text((x + foot_h * 0.45 + a * 0.9, mid), votes_txt, font=small_f, anchor="lm", fill=ink)
    up(x + w1 - foot_h * 0.45, mid, a, down=True)
    x += w1 + int(pad * 0.4)
    com_txt = _compact(comments)
    w2 = int(a * 1.4 + small_f.getlength(com_txt) + foot_h * 0.9)
    d.rounded_rectangle((x, foot_top, x + w2, foot_top + foot_h), radius=r, fill=pill)
    bx, bw, bh = x + foot_h * 0.35, a * 1.15, a * 0.85
    d.rounded_rectangle((bx, mid - bh / 2, bx + bw, mid + bh / 2), radius=int(bh * 0.35), outline=ink,
                        width=max(2, int(U * 0.004)))
    d.polygon([(bx + bw * 0.2, mid + bh / 2 - 1), (bx + bw * 0.2, mid + bh * 0.85), (bx + bw * 0.5, mid + bh / 2 - 1)],
              fill=ink)
    d.text((bx + bw + a * 0.45, mid), com_txt, font=small_f, anchor="lm", fill=ink)
    x += w2 + int(pad * 0.4)
    share = "Share"
    w3 = int(small_f.getlength(share) + foot_h * 0.9)
    if x + w3 <= cw - pad:
        d.rounded_rectangle((x, foot_top, x + w3, foot_top + foot_h), radius=r, fill=pill)
        d.text((x + w3 / 2, mid), share, font=small_f, anchor="mm", fill=ink)

    img.save(dest)
    y0 = int(min(max(H * 0.5 - ch / 2, H * 0.12), max(H * 0.12, H - ch - H * 0.12)))
    return dest, (W - cw) // 2, y0


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
    chat: tuple[Path, int, int] | None = None  # (ffconcat playlist, x, y) for chat stories
    card: tuple[Path, int, int] | None = None  # (png, x, y) post card for Reddit-style stories
    card_until: float = 0.0


def build_overlays(settings: Settings, chunks: list[Chunk], total: float, hook_text: str, work: Path, *,
                   labels: dict[str, str] | None = None, chat: list[ChatMessage] | None = None,
                   contact: str = "", card: tuple[str, str, str] | None = None,
                   card_until: float = 0.0) -> OverlayPlan:
    """labels: speaker name tags over the captions (dialogue). chat: render a text-message screen
    instead of captions (the messages are the captions). card: (community, poster, title) of a post card
    shown until ``card_until`` in place of the hook title (pass captions that start after it)."""
    style = CAPTION_STYLES.get(settings.caption_style, CAPTION_STYLES["bold"])
    if not settings.caption_uppercase and style.font == "anton":
        style = replace(style, font="sans")
    font_path, family = resolve_font(settings, style.font)
    card = card if card and card_until > 0 else None
    hook_until = min(2.8, total * 0.4) if settings.hook_overlay and hook_text and not card else 0.0
    cta_text = settings.end_cta.strip()
    cta_from = max(total - 2.6, total * 0.6) if cta_text else 0.0
    hook_y = 0.09 if chat else 0.15
    chat_plan = None
    if chat:
        if settings.language.split("-")[0] in COMPLEX_LANGS and not features.check("raqm"):
            log.warning("This Pillow build can't shape %s text; chat bubbles may look wrong", settings.language)
        sans, _ = resolve_font(settings, "sans")
        screen = ChatScreen(settings, sans, contact)
        chat_plan = (screen.build(chat, total, work / "chat"), screen.x, screen.y)
        chunks = []
    card_plan = None
    if card:
        if settings.language.split("-")[0] in COMPLEX_LANGS and not features.check("raqm"):
            log.warning("This Pillow build can't shape %s text; the post card may look wrong", settings.language)
        sans, _ = resolve_font(settings, "sans")
        card_plan = post_card_png(settings, sans, *card, work / "card.png")

    if needs_ass(settings) and ffmpeg.has_filter("ass"):
        fonts = work / "fonts"
        fonts.mkdir(parents=True, exist_ok=True)
        if font_path:
            shutil.copy(font_path, fonts / font_path.name)
        ass = write_ass(settings, style, family, chunks, total, work / "captions.ass",
                        hook=hook_text if hook_until else "", hook_until=hook_until,
                        cta=cta_text, cta_from=cta_from, watermark=settings.watermark_text,
                        hook_y=hook_y, cta_y=0.10 if chat else 0.30, labels=labels)
        log.info("Captions: libass renderer (%s, font %s)", settings.language, family)
        return OverlayPlan("ass", ass=ass, fonts_dir=fonts, chat=chat_plan, card=card_plan,
                           card_until=card_until if card_plan else 0.0)

    plan = OverlayPlan("pillow", chat=chat_plan, card=card_plan, card_until=card_until if card_plan else 0.0)
    if chunks:
        caps = PillowCaptions(settings, style, font_path, labels)
        plan.captions, plan.captions_y = caps.build(chunks, total, work / "captions"), caps.band_y
    ui_font, _ = resolve_font(settings, "anton" if settings.caption_uppercase else "sans")
    if hook_until:
        plan.hook = hook_png(settings, ui_font, hook_text, work / "hook.png", y_ratio=hook_y,
                             max_lines=2 if chat else 3)
        plan.hook_until = hook_until
    if settings.watermark_text:
        plan.watermark = watermark_png(settings, ui_font, settings.watermark_text, work / "watermark.png")
    if cta_text:
        # Chat stories keep the conversation readable: the call-to-action takes the hook's place above it.
        plan.cta = cta_png(settings, ui_font, cta_text, work / "cta.png", y_ratio=0.10 if chat else 0.30)
        plan.cta_from = cta_from
    return plan
