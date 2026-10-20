"""Settings: every knob is an environment variable (usually set in .env) and most have a CLI flag.

Old variable names from PurffleShorts 1.x (SHORTS_RESOLUTION, SHORTS_FPS, SHORTS_MUSIC_VOLUME,
SHORTS_CAPTION_FONTSIZE, SHORTS_BATCH_SIZE, SHORTS_BATCH_DELAY, GOOGLE_CLIENT_SECRETS_FILE) still work.
"""

from __future__ import annotations

import os
import re
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


_LANG_CODE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,4})?$")


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
    topic_sources: list[str] = field(default_factory=lambda: ["niche"])  # niche,search,trending,wikipedia,reddit,file
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
    script_review_rounds: int = 1     # rewrite rounds while the score is below script_target_score
    script_target_score: int = 80     # stop improving once a script scores this (0-100)
    learn_from_stats: bool = False    # show the LLM which of your videos got the most / fewest views
    seo_keywords: bool = True         # hand the script writer what people really search for on YouTube

    # --- voice ----------------------------------------------------------------------------
    tts_engine: str = "edge"          # edge|openai|elevenlabs|kokoro|coqui|system|silent
    tts_voice: str = ""               # blank = best default for the language; comma list = rotate
    tts_voice_b: str = ""             # second speaker (dialogue and chat formats); blank = automatic
    tts_rate: str = "+8%"             # edge-tts speaking rate
    tts_model: str = ""               # engine-specific model (e.g. gpt-4o-mini-tts, eleven_multilingual_v2)
    tts_instructions: str = "Energetic, curious storyteller voice for a YouTube Short. Natural pacing."
    align: str = "auto"               # auto|none|faster-whisper|openai — word timing for engines without it
    voice_cache: bool = True          # reuse lines already spoken in the same voice (fast re-renders)
    whisper_model: str = "auto"       # faster-whisper model: auto (large-v3-turbo on a GPU, small on CPU), base...

    # --- visuals --------------------------------------------------------------------------
    visual_sources: list[str] = field(default_factory=lambda: ["pexels", "pixabay"])
    media_dir: str = "media"
    image_model: str = "gpt-image-1"
    visual_style: str = "cinematic, dramatic lighting, highly detailed, vertical composition"
    prefer_4k: bool = False
    background_video: str = ""        # a video file or folder (gameplay, satisfying clips) played under stories
    background_layout: str = "full"   # full = the background is the picture; split = footage on top, it below

    # --- render ---------------------------------------------------------------------------
    resolution: tuple[int, int] = (1080, 1920)
    fps: int = 30
    video_encoder: str = "libx264"    # libx264|h264_videotoolbox|h264_nvenc|auto
    crf: int = 21
    preset: str = "veryfast"
    transition: str = "random"        # random|none|fade|slideup|...
    transition_seconds: float = 0.35
    max_shot_seconds: float = 4.5     # longer scenes are cut into several shots (0 = one shot per scene)
    clip_jump_cuts: bool = True       # clips: shorten long pauses and cut "um" / "uh"
    clip_max_pause: float = 0.6       # clips: pauses longer than this (seconds) are shortened
    clip_zoom: bool = True            # clips: punch in and out between sentences
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
    caption_emphasis: bool = True     # key words and numbers in their own colour
    caption_emoji: bool = True        # an emoji per scene pops up above the captions (Twemoji, CC-BY 4.0)
    music_dir: str = "music"
    music_file: str = "back.mp3"
    music_volume: float = 0.14
    music_ducking: bool = True
    loudness_lufs: float = -14.0
    voice_enhance: bool = True        # rumble cut, de-esser and gentle compression on the voice
    sound_effects: bool = True        # whoosh on scene changes, pop per text message, hit under the hook
    sfx_volume: float = 1.0           # 1.0 = 11 dB under the voice; 0.5 is quieter, 2.0 louder

    # --- YouTube --------------------------------------------------------------------------
    upload: bool = True
    privacy: str = "public"           # public|unlisted|private
    publish_times: list[str] = field(default_factory=list)  # e.g. 09:00,14:00,19:00 -> scheduled
    timezone: str = ""
    daily_upload_limit: int = 6       # a pace; the API gives uploads their own bucket of 100 a day
    made_for_kids: bool = False
    synthetic_media: bool = True      # YouTube "altered or synthetic content" disclosure
    playlist_id: str = ""
    localize_metadata: list[str] = field(default_factory=list)  # e.g. es,pt,hi: translated title + description
    upload_captions: bool = False     # also upload captions.srt as a caption track (400 quota units)
    publish_to: list[str] = field(default_factory=lambda: ["youtube"])  # youtube,tiktok,instagram,...
    upload_post_api_key: str = ""     # upload-post.com relay: TikTok, Instagram, Facebook, Threads, X, ...
    upload_post_user: str = ""        # the Upload-Post profile the accounts are connected to
    tiktok_privacy: str = ""          # PUBLIC_TO_EVERYONE|MUTUAL_FOLLOW_FRIENDS|FOLLOWER_OF_CREATOR|SELF_ONLY
    instagram_user_id: str = ""       # official Instagram API (instead of the relay for Instagram)
    instagram_access_token: str = ""
    instagram_api_version: str = "v25.0"
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
            script_review_rounds=max(1, min(4, _int("SCRIPT_REVIEW_ROUNDS", d.script_review_rounds))),
            script_target_score=max(0, min(100, _int("SCRIPT_TARGET_SCORE", d.script_target_score))),
            learn_from_stats=_bool(_env("LEARN_FROM_STATS", "false")),
            seo_keywords=_bool(_env("SEO_KEYWORDS", "true")),
            tts_engine=_env("TTS_ENGINE", d.tts_engine).lower(),
            tts_voice=_env("TTS_VOICE"),
            tts_voice_b=_env("TTS_VOICE_B"),
            tts_rate=_env("TTS_RATE", d.tts_rate),
            tts_model=_env("TTS_MODEL"),
            tts_instructions=_env("TTS_INSTRUCTIONS", d.tts_instructions),
            align=_env("ALIGN", d.align).lower(),
            voice_cache=_bool(_env("VOICE_CACHE", "true")),
            whisper_model=_env("WHISPER_MODEL", d.whisper_model),
            visual_sources=[v.lower() for v in _list(_env("VISUAL_SOURCES", "pexels,pixabay"))],
            media_dir=_env("MEDIA_DIR", d.media_dir),
            image_model=_env("IMAGE_MODEL", d.image_model),
            visual_style=_env("VISUAL_STYLE", d.visual_style),
            prefer_4k=_bool(_env("PREFER_4K", "false")),
            background_video=_env("BACKGROUND_VIDEO"),
            background_layout=_env("BACKGROUND_LAYOUT", d.background_layout).lower(),
            resolution=resolution,
            fps=max(1, _int("FPS", d.fps, "SHORTS_FPS")),
            video_encoder=_env("VIDEO_ENCODER", d.video_encoder),
            crf=_int("CRF", d.crf),
            preset=_env("PRESET", d.preset),
            transition=_env("TRANSITION", d.transition).lower(),
            transition_seconds=max(0.0, _float("TRANSITION_SECONDS", d.transition_seconds)),
            max_shot_seconds=max(0.0, _float("MAX_SHOT_SECONDS", d.max_shot_seconds)),
            clip_jump_cuts=_bool(_env("CLIP_JUMP_CUTS", "true")),
            clip_max_pause=max(0.2, _float("CLIP_MAX_PAUSE", d.clip_max_pause)),
            clip_zoom=_bool(_env("CLIP_ZOOM", "true")),
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
            caption_emphasis=_bool(_env("CAPTION_EMPHASIS", "true")),
            caption_emoji=_bool(_env("CAPTION_EMOJI", "true")),
            music_dir=_env("MUSIC_DIR", d.music_dir),
            music_file=_env("MUSIC_FILE", d.music_file),
            music_volume=max(0.0, _float("MUSIC_VOLUME", d.music_volume, "SHORTS_MUSIC_VOLUME")),
            music_ducking=_bool(_env("MUSIC_DUCKING", "true")),
            loudness_lufs=_float("LOUDNESS_LUFS", d.loudness_lufs),
            voice_enhance=_bool(_env("VOICE_ENHANCE", "true")),
            sound_effects=_bool(_env("SOUND_EFFECTS", "true")),
            sfx_volume=max(0.0, _float("SFX_VOLUME", d.sfx_volume)),
            upload=_bool(_env("UPLOAD", "true")),
            privacy=_env("YT_PRIVACY", d.privacy).lower(),
            publish_times=_list(_env("PUBLISH_TIMES")),
            timezone=_env("TIMEZONE"),
            daily_upload_limit=_int("YT_DAILY_LIMIT", d.daily_upload_limit),
            made_for_kids=_bool(_env("MADE_FOR_KIDS", "false")),
            synthetic_media=_bool(_env("SYNTHETIC_MEDIA", "true")),
            playlist_id=_env("PLAYLIST_ID"),
            localize_metadata=[v for v in _list(_env("LOCALIZE_METADATA")) if _LANG_CODE.match(v)],
            upload_captions=_bool(_env("UPLOAD_CAPTIONS", "false")),
            publish_to=[v.lower() for v in _list(_env("PUBLISH_TO", "youtube"))] or ["youtube"],
            upload_post_api_key=_env("UPLOAD_POST_API_KEY"),
            upload_post_user=_env("UPLOAD_POST_USER"),
            tiktok_privacy=_env("TIKTOK_PRIVACY").upper(),
            instagram_user_id=_env("INSTAGRAM_USER_ID"),
            instagram_access_token=_env("INSTAGRAM_ACCESS_TOKEN"),
            instagram_api_version=_env("INSTAGRAM_API_VERSION", d.instagram_api_version),
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
        from .crosspost import PLATFORMS, TIKTOK_PRIVACY
        bad = [p for p in s.publish_to if p not in PLATFORMS]
        if bad:
            raise ConfigError(f"PUBLISH_TO: unknown {', '.join(bad)} (choose from {', '.join(PLATFORMS)})")
        if s.tiktok_privacy and s.tiktok_privacy not in TIKTOK_PRIVACY:
            raise ConfigError(f"TIKTOK_PRIVACY={s.tiktok_privacy!r}: choose one of {', '.join(TIKTOK_PRIVACY)}")
        if s.background_layout not in ("full", "split"):
            raise ConfigError(f"BACKGROUND_LAYOUT={s.background_layout!r}: choose full or split")
        if s.script_review not in ("off", "score", "rewrite"):
            s.script_review = {"false": "off", "no": "off", "0": "off", "true": "rewrite"}.get(s.script_review, "rewrite")
        return s


def load_env(env_file: str | None = None) -> None:
    """Load .env (or a named profile file) without overriding variables already set in the shell."""
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is a hard dependency
        return
    if env_file:
        load_dotenv(env_file, override=True)
        return
    # The .env in the folder you run from (or PURFFLE_HOME). Plain load_dotenv() searches upwards from the
    # package's own folder, which never reaches your folder once the package is installed with pip or uvx.
    path = find_dotenv(usecwd=True) or find_dotenv()
    if path:
        load_dotenv(path)
