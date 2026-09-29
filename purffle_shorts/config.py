"""Settings: every knob is an environment variable (usually set in .env) and most have a CLI flag.

Old variable names from PurffleShorts 1.x (SHORTS_RESOLUTION, SHORTS_FPS, SHORTS_MUSIC_VOLUME,
SHORTS_CAPTION_FONTSIZE, SHORTS_BATCH_SIZE, SHORTS_BATCH_DELAY, GOOGLE_CLIENT_SECRETS_FILE) still work.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

DEFAULT_NICHES = [
    "mind-blowing science facts",
    "unsolved mysteries",
    "dark history",
    "space and the universe",
    "psychology tricks",
    "true crime cases",
    "future technology and AI",
    "money and finance tips",
    "animal superpowers",
    "ancient civilizations",
    "the human body",
    "strange but true facts",
    "famous inventions and inventors",
    "ocean mysteries",
    "self-improvement and productivity",
    "cars and engineering",
    "video game history",
    "weird laws around the world",
    "survival facts",
    "motivational stories",
]


def _env(name: str, default: str = "", *aliases: str) -> str:
    for key in (name, *aliases):
        val = os.getenv(key)
        if val is not None and val.strip() != "":
            return val.strip()
    return default


def _bool(val: str | bool) -> bool:
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def _list(val: str) -> list[str]:
    return [v.strip() for v in val.replace(";", ",").split(",") if v.strip()]


class ConfigError(ValueError):
    """A setting has a value that can't be used (reported once, before any work starts)."""


def _int(name: str, default: int, *aliases: str) -> int:
    raw = _env(name, str(default), *aliases)
    try:
        return int(float(raw))
    except ValueError:
        raise ConfigError(f"{name}={raw!r} is not a whole number (default {default})") from None


def _float(name: str, default: float, *aliases: str) -> float:
    raw = _env(name, str(default), *aliases)
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name}={raw!r} is not a number (default {default})") from None


# Aspect presets: 9:16 is a Short/Reel/TikTok, 16:9 a regular YouTube video, 1:1 and 4:5 feed posts.
ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}


def aspect_resolution(aspect: str) -> tuple[int, int] | None:
    return ASPECTS.get(aspect.strip().replace("x", ":").replace("/", ":"))


def parse_resolution(value: str, default: tuple[int, int] = (1080, 1920)) -> tuple[int, int]:
    try:
        w, h = value.lower().replace(" ", "").split("x")
        w_i, h_i = int(w), int(h)
        # Even dimensions are required by yuv420p / libx264.
        return (w_i - w_i % 2, h_i - h_i % 2)
    except Exception:
        return default


@dataclass
class Settings:
    # --- content -------------------------------------------------------------------------
    niches: list[str] = field(default_factory=lambda: list(DEFAULT_NICHES))
    topic_sources: list[str] = field(default_factory=lambda: ["niche"])  # niche,trending,wikipedia,reddit,file
    topics_file: str = "topics.txt"
    trends_geo: str = "US"
    style: str = "auto"               # auto|facts|story|listicle|myth|quiz|motivational|news|explainer|dialogue|chat
    language: str = "en"
    target_seconds: int = 40
    channel_name: str = "PurffleStudios"
    audience: str = "curious general audience"
    rss_feeds: list[str] = field(default_factory=list)   # for TOPIC_SOURCES=rss
    also_languages: list[str] = field(default_factory=list)  # e.g. es,hi -> a translated copy of every video

    # --- LLM ------------------------------------------------------------------------------
    llm_provider: str = "auto"
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_fallbacks: list[str] = field(default_factory=list)
    llm_temperature: float = 0.9
    anthropic_effort: str = ""        # low|medium|high|xhigh|max (blank = API default)
    script_review: str = "rewrite"    # off|score|rewrite — the Script Doctor's second pass
    learn_from_stats: bool = False    # show the LLM which of your videos got the most / fewest views

    # --- voice ----------------------------------------------------------------------------
    tts_engine: str = "edge"          # edge|openai|elevenlabs|kokoro|coqui|system|silent
    tts_voice: str = ""               # blank = best default for the language; comma list = rotate
    tts_voice_b: str = ""             # second speaker (dialogue and chat formats); blank = automatic
    tts_rate: str = "+8%"             # edge-tts speaking rate
    tts_model: str = ""               # engine-specific model (e.g. gpt-4o-mini-tts, eleven_multilingual_v2)
    tts_instructions: str = "Energetic, curious storyteller voice for a YouTube Short. Natural pacing."
    align: str = "auto"               # auto|none|faster-whisper|openai — word timing for engines without it

    # --- visuals --------------------------------------------------------------------------
    visual_sources: list[str] = field(default_factory=lambda: ["pexels", "pixabay"])
    media_dir: str = "media"
    image_model: str = "gpt-image-1"
    visual_style: str = "cinematic, dramatic lighting, highly detailed, vertical composition"
    prefer_4k: bool = False

    # --- render ---------------------------------------------------------------------------
    resolution: tuple[int, int] = (1080, 1920)
    fps: int = 30
    video_encoder: str = "libx264"    # libx264|h264_videotoolbox|h264_nvenc|auto
    crf: int = 21
    preset: str = "veryfast"
    transition: str = "random"        # random|none|fade|slideup|...
    transition_seconds: float = 0.35
    color_grade: str = "vivid"        # none|vivid|cinematic|warm|cool|bw
    ken_burns: bool = True
    progress_bar: bool = True
    hook_overlay: bool = True
    watermark: str = ""               # blank = channel name; "none" = off
    end_cta: str = "Follow for more!"
    caption_style: str = "bold"       # bold|boxed|neon|clean|karaoke|minimal
    caption_position: str = "center"  # upper|center|lower
    caption_font: str = ""
    caption_fontsize: int = 0         # 0 = auto
    caption_max_words: int = 3
    caption_uppercase: bool = True
    music_dir: str = "music"
    music_file: str = "back.mp3"
    music_volume: float = 0.14
    music_ducking: bool = True
    loudness_lufs: float = -14.0

    # --- YouTube --------------------------------------------------------------------------
    upload: bool = True
    privacy: str = "public"           # public|unlisted|private
    publish_times: list[str] = field(default_factory=list)  # e.g. 09:00,14:00,19:00 -> scheduled
    timezone: str = ""
    daily_upload_limit: int = 6       # 10,000 quota units / 1,600 per upload
    made_for_kids: bool = False
    synthetic_media: bool = True      # YouTube "altered or synthetic content" disclosure
    playlist_id: str = ""
    client_secrets: str = "credentials.json"
    token_file: str = "token.json"
    keep_videos: bool = False
    credit_footage: bool = True
    youtube_api_key: str = ""         # optional, only for reading view counts (learn_from_stats)
    notify_webhook: str = ""          # Discord / Slack / any URL: a message per rendered, uploaded or failed video

    # --- automation -----------------------------------------------------------------------
    batch_size: int = 1
    batch_delay: int = 60
    workers: int = 1
    output_dir: str = "output_videos"
    data_dir: str = "data"

    # --- API keys (read from the environment, never logged) --------------------------------
    openai_api_key: str = ""
    pexels_api_key: str = ""
    pixabay_api_key: str = ""
    elevenlabs_api_key: str = ""
    pollinations_api_key: str = ""

    offline: bool = False             # demo mode: no network LLM, generated visuals

    @property
    def width(self) -> int:
        return self.resolution[0]

    @property
    def height(self) -> int:
        return self.resolution[1]

    @property
    def unit(self) -> int:
        """Reference size for text and overlays: the width of a 9:16 frame, capped on wide frames so a
        16:9 or square video gets captions sized to its height instead of its width."""
        return max(2, min(self.width, int(self.height * 0.75)))

    @property
    def vertical(self) -> bool:
        return self.height >= self.width

    @property
    def orientation(self) -> str:
        if self.height > self.width:
            return "portrait"
        return "landscape" if self.width > self.height else "square"

    @property
    def watermark_text(self) -> str:
        if self.watermark.lower() in {"none", "off", "false", "0"}:
            return ""
        return self.watermark or self.channel_name

    @property
    def out_path(self) -> Path:
        p = Path(self.output_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def data_path(self) -> Path:
        p = Path(self.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def with_overrides(self, **kw) -> Settings:
        valid = {f.name for f in fields(self)}
        return replace(self, **{k: v for k, v in kw.items() if k in valid and v is not None})

    @classmethod
    def from_env(cls) -> Settings:
        d = cls()
        aspect = _env("ASPECT")
        resolution = parse_resolution(_env("RESOLUTION", "1080x1920", "SHORTS_RESOLUTION"))
        if aspect:
            preset = aspect_resolution(aspect)
            if not preset:
                raise ConfigError(f"ASPECT={aspect!r}: choose one of {', '.join(ASPECTS)}")
            if not _env("RESOLUTION", "", "SHORTS_RESOLUTION"):
                resolution = preset
        s = cls(
            niches=_list(_env("NICHES")) or list(DEFAULT_NICHES),
            topic_sources=_list(_env("TOPIC_SOURCES", "niche")) or ["niche"],
            topics_file=_env("TOPICS_FILE", d.topics_file),
            trends_geo=_env("TRENDS_GEO", d.trends_geo),
            style=_env("SCRIPT_STYLE", d.style).lower(),
            language=_env("LANGUAGE", d.language).lower(),
            target_seconds=_int("TARGET_SECONDS", d.target_seconds),
            channel_name=_env("CHANNEL_NAME", d.channel_name),
            audience=_env("AUDIENCE", d.audience),
            rss_feeds=_list(_env("RSS_FEEDS")),
            also_languages=[v.lower() for v in _list(_env("ALSO_LANGUAGES"))],
            llm_provider=_env("LLM_PROVIDER", d.llm_provider).lower(),
            llm_model=_env("LLM_MODEL"),
            llm_base_url=_env("LLM_BASE_URL"),
            llm_api_key=_env("LLM_API_KEY"),
            llm_fallbacks=[p.lower() for p in _list(_env("LLM_FALLBACKS"))],
            llm_temperature=_float("LLM_TEMPERATURE", d.llm_temperature),
            anthropic_effort=_env("ANTHROPIC_EFFORT").lower(),
            script_review=_env("SCRIPT_REVIEW", d.script_review).lower(),
            learn_from_stats=_bool(_env("LEARN_FROM_STATS", "false")),
            tts_engine=_env("TTS_ENGINE", d.tts_engine).lower(),
            tts_voice=_env("TTS_VOICE"),
            tts_voice_b=_env("TTS_VOICE_B"),
            tts_rate=_env("TTS_RATE", d.tts_rate),
            tts_model=_env("TTS_MODEL"),
            tts_instructions=_env("TTS_INSTRUCTIONS", d.tts_instructions),
            align=_env("ALIGN", d.align).lower(),
            visual_sources=[v.lower() for v in _list(_env("VISUAL_SOURCES", "pexels,pixabay"))],
            media_dir=_env("MEDIA_DIR", d.media_dir),
            image_model=_env("IMAGE_MODEL", d.image_model),
            visual_style=_env("VISUAL_STYLE", d.visual_style),
            prefer_4k=_bool(_env("PREFER_4K", "false")),
            resolution=resolution,
            fps=max(1, _int("FPS", d.fps, "SHORTS_FPS")),
            video_encoder=_env("VIDEO_ENCODER", d.video_encoder),
            crf=_int("CRF", d.crf),
            preset=_env("PRESET", d.preset),
            transition=_env("TRANSITION", d.transition).lower(),
            transition_seconds=max(0.0, _float("TRANSITION_SECONDS", d.transition_seconds)),
            color_grade=_env("COLOR_GRADE", d.color_grade).lower(),
            ken_burns=_bool(_env("KEN_BURNS", "true")),
            progress_bar=_bool(_env("PROGRESS_BAR", "true")),
            hook_overlay=_bool(_env("HOOK_OVERLAY", "true")),
            watermark=_env("WATERMARK"),
            end_cta=os.getenv("END_CTA", d.end_cta).strip(),  # set END_CTA= (empty) to disable
            caption_style=_env("CAPTION_STYLE", d.caption_style).lower(),
            caption_position=_env("CAPTION_POSITION", d.caption_position).lower(),
            caption_font=_env("CAPTION_FONT"),
            caption_fontsize=_int("CAPTION_FONTSIZE", 0, "SHORTS_CAPTION_FONTSIZE"),
            caption_max_words=max(1, _int("CAPTION_MAX_WORDS", d.caption_max_words)),
            caption_uppercase=_bool(_env("CAPTION_UPPERCASE", "true")),
            music_dir=_env("MUSIC_DIR", d.music_dir),
            music_file=_env("MUSIC_FILE", d.music_file),
            music_volume=max(0.0, _float("MUSIC_VOLUME", d.music_volume, "SHORTS_MUSIC_VOLUME")),
            music_ducking=_bool(_env("MUSIC_DUCKING", "true")),
            loudness_lufs=_float("LOUDNESS_LUFS", d.loudness_lufs),
            upload=_bool(_env("UPLOAD", "true")),
            privacy=_env("YT_PRIVACY", d.privacy).lower(),
            publish_times=_list(_env("PUBLISH_TIMES")),
            timezone=_env("TIMEZONE"),
            daily_upload_limit=_int("YT_DAILY_LIMIT", d.daily_upload_limit),
            made_for_kids=_bool(_env("MADE_FOR_KIDS", "false")),
            synthetic_media=_bool(_env("SYNTHETIC_MEDIA", "true")),
            playlist_id=_env("PLAYLIST_ID"),
            client_secrets=_env("GOOGLE_CLIENT_SECRETS_FILE", d.client_secrets),
            token_file=_env("YT_TOKEN_FILE", d.token_file),
            keep_videos=_bool(_env("KEEP_VIDEOS", "false")),
            credit_footage=_bool(_env("CREDIT_FOOTAGE", "true")),
            batch_size=max(1, _int("BATCH_SIZE", d.batch_size, "SHORTS_BATCH_SIZE")),
            batch_delay=max(0, _int("BATCH_DELAY", d.batch_delay, "SHORTS_BATCH_DELAY")),
            workers=max(1, _int("WORKERS", d.workers)),
            output_dir=_env("OUTPUT_DIR", d.output_dir),
            data_dir=_env("DATA_DIR", d.data_dir),
            openai_api_key=_env("OPENAI_API_KEY"),
            pexels_api_key=_env("PEXELS_API_KEY"),
            pixabay_api_key=_env("PIXABAY_API_KEY"),
            elevenlabs_api_key=_env("ELEVENLABS_API_KEY", "", "XI_API_KEY"),
            pollinations_api_key=_env("POLLINATIONS_API_KEY"),
            youtube_api_key=_env("YOUTUBE_API_KEY"),
            notify_webhook=_env("NOTIFY_WEBHOOK"),
        )
        if s.script_review not in ("off", "score", "rewrite"):
            s.script_review = {"false": "off", "no": "off", "0": "off", "true": "rewrite"}.get(s.script_review, "rewrite")
        return s


def load_env(env_file: str | None = None) -> None:
    """Load .env (or a named profile file) without overriding variables already set in the shell."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a hard dependency
        return
    if env_file:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv()
