# Changelog

## 2.0.0 — 2026-09-22

A rewrite of the whole pipeline.

### Added
- Any LLM for scripts: OpenAI, Anthropic Claude, Google Gemini, Groq, OpenRouter, DeepSeek, Mistral, Together AI, xAI, Ollama, LM Studio and any OpenAI-compatible URL, with a fallback chain (`LLM_FALLBACKS`).
- One structured LLM call per video: hook, scenes with their own footage query and image prompt, title, description, hashtags, tags and category.
- `make --script file.json` renders your own (or an edited) script without calling an LLM. Examples in `examples/`.
- Free Microsoft neural voices (edge-tts) with native word timing as the default; OpenAI, ElevenLabs, Kokoro, Coqui and OS voices as options; optional faster-whisper alignment.
- Word-synced captions with active-word highlight and pop-in, in 6 styles, with libass for complex scripts.
- Per-scene footage from Pexels and Pixabay (portrait first, never reused), your own `media/` folder, OpenAI images or Pollinations.
- ffmpeg-only render: cover crop to 9:16, Ken Burns, transitions, colour grades, hook title, watermark, progress bar, end CTA, music ducking, −14 LUFS loudness.
- Scheduled publishing into time slots, a quota-aware upload queue, the synthetic-media disclosure, playlists.
- Topic sources: niches, Google Trends, Wikipedia "On this day", Reddit TIL, your own list, with repeats and sensitive news filtered out.
- Studio web dashboard, `doctor`, `providers`, `voices`, `history` and `upload` commands, SQLite history, Docker image, CI on Python 3.10–3.13 with an offline end-to-end render.
- `doctor` reports whether the Ollama model is pulled; with no `LLM_MODEL`, Ollama uses a model you already have instead of failing.

### Changed
- Pollinations images are requested one at a time, since the free tier rejects parallel requests with HTTP 429.
- `OLLAMA_HOST` works without `http://` (for example `127.0.0.1:11434`).

### Removed
- MoviePy, ImageMagick and Coqui as hard requirements; `el.py` and `ytt.py`.

### Upgrading from 1.x
`python YT.py`, `--once`, `--no-upload`, `--count N` and the `SHORTS_*` variables still work, and `token.pickle` is migrated to `token.json` automatically. Install the new requirements first.

## 1.x — 2026-06

The original MoviePy + OpenAI + Coqui TTS pipeline.
