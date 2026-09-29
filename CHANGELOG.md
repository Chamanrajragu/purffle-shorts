# Changelog

## 3.0.0 — 2026-09-29

### Added
- **Script Doctor**: a second LLM pass scores each script 0–100 for retention (hook, pacing, payoff, accuracy risk), lists the problems and rewrites it (`SCRIPT_REVIEW=rewrite|score|off`, `--no-review`). A rewrite that misses the target length is ignored, and a failed review never fails the video. The score is saved in `metadata.json`, the history and the Studio.
- **Two new formats**: `dialogue` (two voices, speaker name tags, a colour per speaker) and `chat` (an animated text-message screen with typing indicators and scrolling). Lines are voiced one by one with `TTS_VOICE` / `TTS_VOICE_B` (or a contrasting voice per language) and trimmed to the spoken part, so conversations have natural pauses. Examples in `examples/chat-story.json` and `examples/dialogue.json`; `demo --style chat|dialogue` works with no keys.
- **`clip` command**: turn a long video (file, or URL with yt-dlp) into Shorts. faster-whisper or OpenAI transcribes it, the LLM picks self-contained moments on sentence boundaries with titles and scores, and each clip is cropped (`--crop center|blur`), captioned and loudness-normalised. Without an LLM the moments are evenly spaced.
- **New sources**: `make --url` (a web page's article text), `make --from-file` (.txt/.md/.html), `TOPIC_SOURCES=rss` with `RSS_FEEDS`.
- **Content planner**: `plan --count N` fills an idea queue that `run` and `make` use first; `ideas` lists and edits it. A failed video returns its idea to the queue.
- **Translated copies**: `ALSO_LANGUAGES` / `--also-lang es,hi` makes each video in more languages with native voices, reusing the original's footage; copies are linked to the original.
- **Aspect presets**: `ASPECT` / `--aspect 9:16|16:9|1:1|4:5`. Captions and overlays are sized for the frame, stock searches and AI images follow its orientation, and 16:9 videos drop `#shorts`.
- **Learn from your channel** (opt-in `LEARN_FROM_STATS`): `stats` reads view, like and comment counts (with `YOUTUBE_API_KEY`, or OAuth read access), and the best and worst performers go into the writing and planning prompts.
- **MCP server** (`purffle-shorts mcp`, standard library only): `make_short`, `draft_script`, `clip_video`, `plan_ideas`, `list_videos`, `upload_video` for Claude Desktop, Claude Code, Cursor and other MCP clients. Uploads only when asked; `demo: true` needs no keys. `PURFFLE_HOME` sets its working folder.
- **Notifications**: `NOTIFY_WEBHOOK` posts to Discord, Slack or any URL when a video is rendered, uploaded, scheduled, queued or fails. Webhook tokens are redacted from logs.
- `POLLINATIONS_API_KEY`, sent as a Bearer token (untested: no key was available while building this).

### Changed
- **New Studio web app**, rewritten from scratch: Create (sources, format cards, shape, voices, caption-style preview, AI settings), draft-then-edit script editor with the retention score, live stage progress, a Library with player, downloads and edit/re-render/upload/delete, Queue, Ideas, Clip, Channel stats and System checks. Served from `purffle_shorts/web/` with no build step or CDN, a strict Content-Security-Policy, a Host-header check against DNS rebinding and the per-session token. Works on phones.
- The pipeline is split into `Studio.draft()` (topic, script, review) and `Studio.produce()` (voice to upload), with progress events.
- Setting values that aren't numbers now stop with `Setting problem: NAME='value' …` instead of a traceback.
- A hardware encoder (`h264_videotoolbox`, `h264_nvenc`) that fails is retried once with libx264.
- The history database gains an idea queue, scores, stats and translation links, and older databases are migrated on open.
- `doctor` checks are shared with the Studio and cover the new features.
- Pollinations: after an HTTP 402 ("payment required", which keyless requests now get after about one image) or another refusal, it is skipped for the rest of the video with one clear message. The README no longer calls it free and keyless.

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
