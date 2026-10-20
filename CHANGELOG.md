# Changelog

## Unreleased

### Added
- **A new Studio design and logo.**
  - Warm paper-and-ink colours with one signal colour, the red of a camera's tally light, in a light theme, a dark "control room" theme, or the system's choice (switch in the sidebar).
  - Schibsted Grotesk and JetBrains Mono, bundled as Latin subsets under the OFL, so nothing loads from a CDN.
  - A numbered brief on the Create page, with a line drawing for each format, and a program monitor that previews the caption style, shape and safe area.
  - An edit-timeline progress display on Create and in the Queue, and the library as a contact sheet. A record-style **Create video** button (⌘↵).
  - `#library/<id>` links that open a video directly.
  - The new mark (a "P" whose bowl is a play button) in `docs/logo.svg`, `docs/logo-dark.svg` and the favicon, and a new `docs/social-preview.png`.
- **TikTok, Instagram Reels and more** (`PUBLISH_TO=youtube,tiktok,instagram`, `--publish-to`). Each video goes to every listed network with a caption cut to that network's length and without `#shorts`, at the same publish slot as YouTube.
  - TikTok and Facebook, Threads, X, LinkedIn, Bluesky and Pinterest go through the Upload-Post relay (`UPLOAD_POST_API_KEY`, `UPLOAD_POST_USER`, `TIKTOK_PRIVACY`). TikTok's own API only lets audited apps publish public videos.
  - Instagram can instead use its official API (`INSTAGRAM_USER_ID`, `INSTAGRAM_ACCESS_TOKEN`), with a resumable upload straight from your computer.
  - Each network's result (posted, scheduled, submitted, draft, failed or skipped) is saved in `metadata.json` and shown in the Studio.
  - `upload --id N` and the Studio's **Publish the rest** re-send only what failed, and never upload to YouTube twice. The MP4 is kept until every destination has it.
  - Tested against recorded API responses, not yet against live TikTok or Instagram accounts.
- **Sound effects**, made in code (no files to license): a whoosh on each scene change, a pop as each text message lands, a low hit under the hook. They are placed 11 dB under the voice, measured after the voice clean-up, so the balance is the same whichever TTS engine spoke (`SOUND_EFFECTS`, `SFX_VOLUME`, `--no-sfx`).
- **Key-word emphasis**: the script writer marks the one or two words that carry each scene (a strict-schema field), and numbers are always included. Both caption renderers draw them in each style's emphasis colour (`CAPTION_EMPHASIS`).
- **Emoji**: one emoji per scene pops up above the captions as the scene starts (Twemoji images, downloaded once and credited in the description; `CAPTION_EMOJI`, `--no-emoji`).
- **Background videos for stories** (`BACKGROUND_VIDEO`, `--background`): one continuous random stretch of a video, or of a random video from a folder (such as gameplay), plays under the whole Short. `BACKGROUND_LAYOUT=full` makes it the picture; `split` puts the scene footage in the top half (searched in that half's shape) and the background below.
- **Clip editing**: jump cuts shorten pauses over `CLIP_MAX_PAUSE` (0.6 s) and remove hesitations ("um", "uh", "eh", "äh", "euh", "hum"). Cuts land on frame boundaries, and the audio is split into frame-long packets, so picture and sound are cut at the same instants (a test with flashes and beeps keeps them within one frame). Also punch-in zoom between sentences (`CLIP_ZOOM`), `clip --prompt "the funniest moments"` to steer which moments are picked, and the virality score with its reason in the CLI, Studio and MCP.
- **Real YouTube searches**: `TOPIC_SOURCES=search` gives the script writer questions people type into YouTube about your niches, and it answers the one that fits. For every video, YouTube's autocomplete phrases for the topic are handed to the writer for the title, description and tags (`SEO_KEYWORDS`, on by default). The planner gets them too. Off-topic, sensitive and adult suggestions are filtered out.
- **Localised titles and descriptions** (`LOCALIZE_METADATA=es,pt,hi`): sent with the upload as YouTube localizations, so viewers whose YouTube is in those languages see the video under a title in their own language.
- **Caption tracks**: `UPLOAD_CAPTIONS=true` uploads `captions.srt` to the video. If the saved sign-in predates the setting, the upload is skipped with a hint to run `auth`.
- **Google Colab notebook** (`notebooks/PurffleShorts.ipynb`): demo, make and clip in the browser with keys from Colab Secrets.
- **REST API documentation** (`docs/api.md`) with curl, Python and n8n examples. `STUDIO_TOKEN` fixes the write token for automation.
- **docker-compose.yml** for the Studio and the autopilot on a server, using the published GHCR image.
- **Fast pacing**: scenes longer than `MAX_SHOT_SECONDS` (4.5 s) are cut into several shots with different footage. Each cut lands on the start of a spoken word near the ideal point, preferring the pauses after commas and sentence ends; shots of one scene hard-cut, scenes keep their transitions. With AI images, the extra shots reuse the scene's picture with a new camera move instead of paying for another image.
- **Footage relevance**: candidates are scored by how well their own description (Pexels page slug and photo alt text, Pixabay tags) matches the scene's query, with word-form matching, plus the search engine's ranking, before shape, length and resolution.
- **Script Doctor 2.0**: a six-part rubric (hook, curiosity, pacing, specificity, payoff, accuracy) gives the weighted 0–100 score; deterministic checks (hook length, greetings, length vs. target, missing call to action, long sentences, repeated words, filler, no concrete number) are fed into the review and listed with the result; the rewrite is graded again and dropped if it scores lower than the draft, so the stored score is always that of the script used. Grading runs at temperature 0.2 for repeatable scores. `SCRIPT_REVIEW_ROUNDS` and `SCRIPT_TARGET_SCORE` allow extra rounds. Sub-scores are saved in `metadata.json` and shown in the Studio.
- **Two-pass loudness** in a separate soundtrack pass (measure, then one linear gain), and gentle voice clean-up (`VOICE_ENHANCE`: rumble cut, de-esser, compression). Measured on a real render: −14.0 LUFS integrated, −1.5 dBFS peak.
- **Pause-anchored timing**: voices without word timestamps and no aligner get their sentence and clause ends pinned to the pauses ffmpeg finds in the audio; only the words in between are estimated (on a test with known pauses, the mean boundary error went from 0.24 s to under 0.01 s).
- `WHISPER_MODEL` (default `auto`: `large-v3-turbo` on an NVIDIA GPU, `small` on CPU, was fixed `base`), voice-activity detection for `clip`, and the script text as a hint when aligning a voice.
- **Strict JSON-schema output** for OpenAI, Gemini, OpenRouter, Ollama and LM Studio, stepping down to JSON mode and then to plain parsing when an endpoint refuses it (`LLM_JSON_SCHEMA=false` to turn off).
- **Face framing for clips** (`clip --crop face`, `pip install opencv-python-headless`): the YuNet face detector (or OpenCV 4's Haar cascade) samples the clip twice a second, a running median removes stray detections, and the crop keeps one steady framing per camera shot.
- **Best-frame cover**: the cover is the sharpest, best-exposed, most colourful frame while the hook is on screen, never one blended by a transition.
- **Live Studio**: jobs are pushed over Server-Sent Events (polling remains as a fallback), running jobs show a percentage and the time left, learned per stage from this machine's own renders, and **Cancel** now stops a running job (ffmpeg is stopped at once; nothing half-made is kept).
- A live progress line in the terminal for `make`, `demo`, `run` and `clip`.
- **Voice cache**: lines already spoken in the same voice are reused (`VOICE_CACHE`, size-limited), so re-rendering an edited script only voices what changed.
- **Learning loop**: with `LEARN_FROM_STATS`, `SCRIPT_STYLE=auto` picks the format by Thompson sampling over the channel's own view counts; `stats` and the Channel page report whether the retention score predicts views (Spearman correlation), median views per format and the best publish hours.
- `STUDIO_PASSWORD` (HTTP Basic) for a Studio that runs on a server.

### Fixed
- Transcription with faster-whisper 1.2.1 failed under a newer PyAV ("unexpected keyword argument 'metadata_errors'"). Audio is now decoded by PurffleShorts' own ffmpeg and passed to Whisper as samples.
- A Studio API request could upload even with `UPLOAD=false` in `.env`; that setting is now a hard stop for API jobs too.

### Changed
- A Studio page whose server is stopped retries less and less often (up to every 30 s) instead of every 1.5 s, and after a server restart an action explains that the page needs a reload instead of showing "bad token".
- `doctor` and the Studio's System page report the background video, retention editing, SEO and clip-editing settings. A full-screen background video no longer counts as "no footage".
- The example scripts carry key words and emoji.
- The content planner is told that ideas must be true and checkable: no invented people and no miracle health or money claims. A small local model had suggested one.
- Renders take about 40% less time on the same machine (offline 1080×1920 demo, median of 3 runs: facts 26.0 s → 15.5 s, chat story 27.1 s → 16.8 s), while now cutting about twice as many shots: overlays blend in the output's own pixel format instead of converting every frame, the end card only exists while it is visible, generated backgrounds are drawn small and scaled up (10 s → 2.7 s each), intermediates use the `ultrafast` preset, and caption and chat frames are drawn on several threads.
- The Anthropic default model is `claude-opus-5-5`, at effort `high` unless `ANTHROPIC_EFFORT` is set (its API default is `medium`); server-side refusal fallbacks also cover Claude Sonnet 5.5; a reply cut off at the token limit is reported as such.
- Translations (temperature 0.4) and clip picking (0.3) run cooler than script writing.
- The history database uses WAL mode with indexes, so the Studio reads while a job writes; "YouTube refused uploads today" is stored there, so every Studio job, a restarted autopilot and the MCP server all respect it.
- `doctor` reports the Script Doctor mode, voice cache, pacing, Whisper model and face framing.

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
- **Reddit-style story format** (`reddit`): a first-person story that opens on a post card (community, poster, title, vote and comment counts) while the title is read, then continues with word captions. The card replaces the hook title, works in every aspect ratio and in libass mode, and the SRT keeps the whole narration. Example in `examples/reddit-story.json`; `demo --style reddit` works with no keys.
- `make --url` accepts Reddit post links. Reddit refuses anonymous JSON requests, so the post is read from its public Atom feed, and the Reddit story format is picked automatically. A rate-limited request (HTTP 429) gets a clear message.
- `POLLINATIONS_API_KEY`, sent as a Bearer token (untested: no key was available while building this).
- Release automation (`.github/workflows/release.yml`): publishing a GitHub release builds the package, publishes it to PyPI with Trusted Publishing, lists the MCP server in the official MCP Registry (`server.json`) and pushes a Docker image to GHCR. `glama.json` for the Glama MCP directory.
- CI also builds the Docker image and checks the PyPI package (`twine check --strict`).
- `CODE_OF_CONDUCT.md`, `CITATION.cff` and a pull request template.

### Changed
- **New Studio web app**, rewritten from scratch: Create (sources, format cards, shape, voices, caption-style preview, AI settings), draft-then-edit script editor with the retention score, live stage progress, a Library with player, downloads and edit/re-render/upload/delete, Queue, Ideas, Clip, Channel stats and System checks. Served from `purffle_shorts/web/` with no build step or CDN, a strict Content-Security-Policy, a Host-header check against DNS rebinding and the per-session token. Works on phones.
- The pipeline is split into `Studio.draft()` (topic, script, review) and `Studio.produce()` (voice to upload), with progress events.
- Setting values that aren't numbers now stop with `Setting problem: NAME='value' …` instead of a traceback.
- A hardware encoder (`h264_videotoolbox`, `h264_nvenc`) that fails is retried once with libx264.
- The history database gains an idea queue, scores, stats and translation links, and older databases are migrated on open.
- `doctor` checks are shared with the Studio and cover the new features.
- Installing on an Intel Mac no longer tries to compile `cryptography` (its newest releases ship no Intel-Mac wheels): it is capped below 49 there.
- Packaging: SPDX license metadata (`license = "MIT"`), the Studio's web files are declared as package data, and the build has no warnings.
- The YouTube upload limit is explained correctly: uploads now have their own API bucket of 100 a day, so `YT_DAILY_LIMIT=6` is a pace, not a quota ceiling.
- The Studio labels Pollinations as needing a key, and the Dockerfile has OCI labels and its Studio example publishes the port on localhost only.
- Pollinations: after an HTTP 402 ("payment required", which keyless requests now get after about one image) or another refusal, it is skipped for the rest of the video with one clear message. The README no longer calls it free and keyless.

### Fixed
- `.env` is now read from the folder you run PurffleShorts in (or `PURFFLE_HOME`). Before, it was searched for next to the installed package, so installs with pip, pipx or uvx, and MCP clients, started without your keys.
- YouTube's `uploadLimitExceeded` refusal (an HTTP 400) now queues the video like `quotaExceeded` instead of marking it failed, and after any such refusal nothing else is tried until the reset, so autopilot waits instead of making videos that cannot go up.
- Without an LLM, `clip` spreads its moments over the whole video instead of taking the first minutes back to back.
- `.env.example` keeps every comment on its own line, so it also works with `docker run --env-file` (which reads a comment after a value as part of the value). It lists `reddit` and `YT_TOKEN_FILE`, and says that `PURFFLE_HOME` belongs in the MCP client's settings.

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
