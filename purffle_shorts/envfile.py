"""Read and edit the .env file from the Studio's Settings page.

Desktop users never have to open a text editor: every setting the Studio shows is listed in SCHEMA, values are
written back into .env in place (comments, order and unknown lines are kept), and the running process picks
them up at once. API keys are never sent to the browser: the page only learns whether a key is set and its
last four characters.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")

# kind: secret | text | select | bool | number | list | path
SCHEMA: list[dict] = [
    {"group": "AI writer", "id": "ai", "intro": "Which model writes and reviews the scripts. Local models are "
     "free and private; cloud models are faster and usually write better hooks.", "fields": [
        {"key": "LLM_PROVIDER", "label": "Provider", "kind": "select", "default": "auto",
         "options": ["auto", "ollama", "lmstudio", "openai", "anthropic", "gemini", "groq", "openrouter",
                     "deepseek", "mistral", "together", "xai", "custom"],
         "help": "auto uses the first cloud key it finds, then Ollama if it is running."},
        {"key": "LLM_MODEL", "label": "Model", "kind": "text", "placeholder": "provider default",
         "help": "For Ollama, any installed model (see Local AI)."},
        {"key": "LLM_FALLBACKS", "label": "Fallbacks", "kind": "list", "placeholder": "e.g. ollama,gemini",
         "help": "Tried in order when the main provider fails."},
        {"key": "SCRIPT_REVIEW", "label": "Script Doctor", "kind": "select", "default": "rewrite",
         "options": ["off", "score", "rewrite"]},
        {"key": "LOCAL_THINKING", "label": "Let local models think", "kind": "bool", "default": "false",
         "help": "Reasoning models (qwen3, deepseek-r1) answer better but can take many minutes on a CPU."},
        {"key": "OPENAI_API_KEY", "label": "OpenAI key", "kind": "secret", "link": "https://platform.openai.com/api-keys"},
        {"key": "ANTHROPIC_API_KEY", "label": "Anthropic key", "kind": "secret",
         "link": "https://console.anthropic.com/settings/keys"},
        {"key": "GEMINI_API_KEY", "label": "Google Gemini key", "kind": "secret",
         "link": "https://aistudio.google.com/apikey", "help": "Has a free tier."},
        {"key": "GROQ_API_KEY", "label": "Groq key", "kind": "secret", "link": "https://console.groq.com/keys",
         "help": "Has a free tier, very fast."},
        {"key": "OPENROUTER_API_KEY", "label": "OpenRouter key", "kind": "secret", "link": "https://openrouter.ai/keys"},
        {"key": "DEEPSEEK_API_KEY", "label": "DeepSeek key", "kind": "secret"},
        {"key": "MISTRAL_API_KEY", "label": "Mistral key", "kind": "secret"},
        {"key": "TOGETHER_API_KEY", "label": "Together AI key", "kind": "secret"},
        {"key": "XAI_API_KEY", "label": "xAI key", "kind": "secret"},
        {"key": "OLLAMA_HOST", "label": "Ollama address", "kind": "text", "placeholder": "http://localhost:11434"},
        {"key": "LLM_BASE_URL", "label": "Custom OpenAI-compatible URL", "kind": "text",
         "placeholder": "https://…/v1"},
        {"key": "LLM_API_KEY", "label": "Custom URL key", "kind": "secret"},
    ]},
    {"group": "Voice", "id": "voice", "intro": "Who reads the script.", "fields": [
        {"key": "TTS_ENGINE", "label": "Voice engine", "kind": "select", "default": "edge",
         "options": ["edge", "kokoro", "system", "openai", "elevenlabs", "coqui"],
         "help": "edge is free online; kokoro and system work offline."},
        {"key": "TTS_VOICE", "label": "Voice", "kind": "text", "placeholder": "picked for the language"},
        {"key": "TTS_RATE", "label": "Speed", "kind": "text", "default": "+8%", "placeholder": "+8%"},
        {"key": "ELEVENLABS_API_KEY", "label": "ElevenLabs key", "kind": "secret",
         "link": "https://elevenlabs.io/app/settings/api-keys"},
        {"key": "WHISPER_MODEL", "label": "Transcription model", "kind": "select", "default": "auto",
         "options": ["auto", "tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"],
         "help": "faster-whisper, for clipping long videos and word timing."},
    ]},
    {"group": "Footage", "id": "footage", "intro": "Where the pictures come from. Pexels and Pixabay keys are "
     "free and take a minute to get.", "fields": [
        {"key": "VISUAL_SOURCES", "label": "Sources, in order", "kind": "list", "default": "pexels,pixabay",
         "help": "pexels, pixabay, local, pollinations, openai-images"},
        {"key": "PEXELS_API_KEY", "label": "Pexels key", "kind": "secret", "link": "https://www.pexels.com/api/new/"},
        {"key": "PIXABAY_API_KEY", "label": "Pixabay key", "kind": "secret",
         "link": "https://pixabay.com/api/docs/"},
        {"key": "POLLINATIONS_API_KEY", "label": "Pollinations key (AI images)", "kind": "secret",
         "link": "https://auth.pollinations.ai"},
        {"key": "MEDIA_DIR", "label": "My media folder", "kind": "path", "default": "media"},
        {"key": "BACKGROUND_VIDEO", "label": "Background video", "kind": "path",
         "help": "A file, or a folder to pick one from at random."},
        {"key": "MUSIC_DIR", "label": "Music folder", "kind": "path", "default": "music"},
    ]},
    {"group": "Channel", "id": "channel", "intro": "What your videos are about and how they sign off.", "fields": [
        {"key": "CHANNEL_NAME", "label": "Channel name", "kind": "text", "default": "PurffleStudios"},
        {"key": "NICHES", "label": "Niches", "kind": "list",
         "placeholder": "space facts, dark history, psychology tricks",
         "help": "Topics the AI picks from when you don't give one."},
        {"key": "AUDIENCE", "label": "Audience", "kind": "text", "default": "curious general audience"},
        {"key": "LANGUAGE", "label": "Language", "kind": "text", "default": "en"},
        {"key": "TARGET_SECONDS", "label": "Length (seconds)", "kind": "number", "default": "40"},
        {"key": "WATERMARK", "label": "Watermark", "kind": "text", "placeholder": "@yourhandle"},
        {"key": "END_CTA", "label": "Closing line", "kind": "text", "default": "Follow for more!"},
        {"key": "CREDIT_LINE", "label": "Credit PurffleShorts", "kind": "bool", "default": "false",
         "help": "End descriptions with \"Made with PurffleShorts\" and its link. Helps other creators find it."},
    ]},
    {"group": "Video", "id": "video", "intro": "The look of every render.", "fields": [
        {"key": "ASPECT", "label": "Aspect", "kind": "select", "default": "9:16",
         "options": ["9:16", "16:9", "1:1", "4:5"]},
        {"key": "CAPTION_STYLE", "label": "Caption style", "kind": "select", "default": "bold",
         "options": ["bold", "boxed", "neon", "clean", "karaoke", "minimal"]},
        {"key": "COLOR_GRADE", "label": "Colour grade", "kind": "select", "default": "vivid",
         "options": ["none", "vivid", "cinematic", "warm", "cool", "bw"]},
        {"key": "MUSIC_VOLUME", "label": "Music volume", "kind": "number", "default": "0.14"},
        {"key": "VIDEO_ENCODER", "label": "Encoder", "kind": "select", "default": "libx264",
         "options": ["libx264", "auto", "h264_videotoolbox", "h264_nvenc"],
         "help": "Hardware encoders render faster: videotoolbox (Mac), nvenc (NVIDIA). auto picks for you."},
        {"key": "CRF", "label": "Quality (CRF, lower is better)", "kind": "number", "default": "21"},
    ]},
    {"group": "Publishing", "id": "publishing", "intro": "Where finished videos go. Switch off Allow publishing to only make files.",
     "fields": [
        {"key": "UPLOAD", "label": "Allow publishing", "kind": "bool", "default": "true"},
        {"key": "PUBLISH_TO", "label": "Networks", "kind": "list", "default": "youtube",
         "help": "youtube, tiktok, instagram, facebook, threads, x, linkedin, pinterest, bluesky"},
        {"key": "YT_PRIVACY", "label": "YouTube privacy", "kind": "select", "default": "public",
         "options": ["public", "unlisted", "private"]},
        {"key": "PUBLISH_TIMES", "label": "Schedule times", "kind": "list", "placeholder": "09:00, 18:00"},
        {"key": "YT_DAILY_LIMIT", "label": "Uploads per day", "kind": "number", "default": "6"},
        {"key": "GOOGLE_CLIENT_SECRETS_FILE", "label": "YouTube OAuth file", "kind": "path",
         "default": "credentials.json"},
        {"key": "YOUTUBE_API_KEY", "label": "YouTube Data API key", "kind": "secret",
         "help": "Optional, for reading channel stats."},
        {"key": "LEARN_FROM_STATS", "label": "Learn from my stats", "kind": "bool", "default": "false",
         "help": "New scripts see which of your videos got the most and fewest views."},
        {"key": "UPLOAD_POST_API_KEY", "label": "Upload-Post key", "kind": "secret",
         "link": "https://upload-post.com", "help": "Posts to TikTok, Instagram and more."},
        {"key": "UPLOAD_POST_USER", "label": "Upload-Post profile", "kind": "text"},
        {"key": "INSTAGRAM_USER_ID", "label": "Instagram user id", "kind": "text"},
        {"key": "INSTAGRAM_ACCESS_TOKEN", "label": "Instagram token", "kind": "secret"},
        {"key": "NOTIFY_WEBHOOK", "label": "Notify webhook", "kind": "secret",
         "help": "Discord, Slack or any URL; told when a video is ready or fails."},
    ]},
    {"group": "App", "id": "app", "intro": "The Studio itself.", "fields": [
        {"key": "CHECK_UPDATES", "label": "Check for updates", "kind": "bool", "default": "true",
         "help": "Once a day, ask GitHub whether a newer version is out (nothing about you is sent)."},
    ]},
]

FIELDS: dict[str, dict] = {f["key"]: f for g in SCHEMA for f in g["fields"]}


def env_path() -> Path:
    """The .env the app reads: the one in the working folder (PURFFLE_HOME), created there when missing."""
    return Path.cwd() / ".env"


def parse(text: str) -> dict[str, str]:
    """KEY=value pairs from .env text (quotes removed, # comments after unquoted values dropped)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = KEY_RE.match(line)
        if m:
            out[m.group(1)] = _unquote(m.group(2))
    return out


def _unquote(raw: str) -> str:
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\") if v[0] == '"' else inner
    return re.split(r"\s+#", v, maxsplit=1)[0].strip()


def _quote(value: str) -> str:
    if value == "" or re.fullmatch(r"[\w.,:/@%+*~=-]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read(path: Path | None = None) -> dict[str, str]:
    p = path or env_path()
    try:
        return parse(p.read_text(encoding="utf-8"))
    except OSError:
        return {}


def write(updates: dict[str, str | None], path: Path | None = None) -> Path:
    """Set (or, with None, remove) keys in .env, keeping every other line as it was."""
    p = path or env_path()
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = ["# PurffleShorts settings (edited from the Studio's Settings page)"]
    left = dict(updates)
    out: list[str] = []
    for line in lines:
        m = KEY_RE.match(line)
        if m and m.group(1) in left:
            value = left.pop(m.group(1))
            if value is not None:
                out.append(f"{m.group(1)}={_quote(value)}")
            continue
        out.append(line)
    for key, value in left.items():
        if value is not None:
            out.append(f"{key}={_quote(value)}")
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text("\n".join(out).rstrip("\n") + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # it holds API keys
    except OSError:
        pass
    os.replace(tmp, p)
    return p


def mask(value: str) -> str:
    return ("•" * 6 + value[-4:]) if len(value) > 8 else ("•" * 6 if value else "")


def current() -> dict:
    """What the Settings page shows: every schema field with its value (keys masked) and where it comes from."""
    in_file = read()
    groups = []
    for g in SCHEMA:
        fields = []
        for f in g["fields"]:
            key = f["key"]
            value = os.getenv(key, "")
            item = {k: v for k, v in f.items()}
            item["source"] = "file" if key in in_file else ("environment" if value else "default")
            if f["kind"] == "secret":
                item["set"] = bool(value)
                item["value"] = mask(value)
            else:
                item["value"] = value
            fields.append(item)
        groups.append({**{k: v for k, v in g.items() if k != "fields"}, "fields": fields})
    return {"path": str(env_path()), "exists": env_path().exists(), "groups": groups}


def clean(values: dict) -> dict[str, str | None]:
    """Validate a save from the Settings page: only known keys, sane lengths, no line breaks.

    A secret sent as null is left alone (the page never had it); "" removes a key."""
    out: dict[str, str | None] = {}
    for key, raw in values.items():
        f = FIELDS.get(key)
        if f is None or (raw is None and f["kind"] == "secret"):
            continue
        if isinstance(raw, bool):
            raw = "true" if raw else "false"
        value = re.sub(r"[\r\n]+", " ", str(raw if raw is not None else "")).strip()[:2000]
        if f["kind"] == "select" and value and value not in f["options"]:
            raise ValueError(f"{f['label']}: choose one of {', '.join(f['options'])}")
        if f["kind"] == "number" and value:
            try:
                float(value)
            except ValueError:
                raise ValueError(f"{f['label']}: {value!r} is not a number") from None
        out[key] = value or None
    return out


def apply(updates: dict[str, str | None]) -> None:
    """Make saved values take effect in this process (a .env value beats an older one loaded at start)."""
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
