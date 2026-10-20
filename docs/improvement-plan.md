# PurffleShorts — audit and improvement plan (3.0 → next)

Written 19 Oct 2026 after reading every module, running the full test suite (128 passed, ruff clean) and
profiling a render on this machine (Intel i9-9880H, 16 threads, ffmpeg 9.0.2).

## What is already good

- **Clear pipeline** (`Studio.draft` → `Studio.produce`) with progress events, typed `Result`s and one
  history database. The modules are small and single-purpose.
- **Robust by design**: retries with backoff, permanent vs retryable errors, LLM fallback chain, voice
  engine fallbacks, a scene always gets *something*, render self-check, hardware-encoder retry, quota
  awareness, failed ideas go back to the queue.
- **Word-accurate captions** when the voice gives timings (edge-tts, ElevenLabs), with script-token
  transfer so captions keep the script's exact wording.
- **Security basics** in the Studio (Host check, per-session token, CSP, no CDN) and secrets redacted
  from logs.
- **Good tests**: offline end-to-end renders, fakes for the keyed path, Studio API tests.

## What is weak (found in the audit)

### Accuracy / output quality
1. **Footage relevance is ignored.** `_score()` ranks candidates only by shape, length and resolution
   plus random jitter. The search API's own relevance order and the clip's description (Pexels page
   slug / photo `alt`, Pixabay `tags`) are thrown away, so a weaker match often wins.
2. **Shots are too long.** A scene is one shot however long it lasts. Retention editing cuts every 2–4 s;
   a 9-second sentence over one stock clip feels slow.
3. **Loudness is approximate.** `loudnorm` runs single-pass inside the video render, which is known to
   miss the target by 1–3 LU and to pump. No voice clean-up (rumble, harshness).
4. **Estimated timing is blind.** Voices without word timings (OpenAI, Kokoro, Coqui, system) and no
   aligner get timings spread by word length only; pauses in the real audio are not used.
5. **Whisper is fixed to the `base` model** with no VAD and no hint of the known script, so clipping and
   alignment accuracy are capped even on a strong machine or a GPU.
6. **Script Doctor score is a single number from one call** — noisy and not explainable. Nothing
   deterministic checks the script (hook length, filler, pace, CTA, repeated words).
7. **JSON reliability**: OpenAI-compatible providers get `json_object` mode only; strict JSON-schema
   structured output (OpenAI, Gemini, Ollama, LM Studio) is never used.
8. **Cover image** is whatever frame is at 1.2 s, even if it's blurry, dark or mid-transition.
9. **Clip crop** is a fixed centre crop, which cuts off a speaker who sits off-centre.
10. **Claude defaults are a generation old**: `claude-opus-5` instead of `claude-opus-5-5`, and
    Sonnet 5.5 doesn't get server-side refusal fallbacks.

### Performance (measured: 1080×1920, offline demo, ~30 s video → 36 s total)
11. Generated gradient backgrounds take **~10 s per scene** (the `gradients` filter at full resolution).
12. Intermediate segments are encoded at `veryfast`/CRF 16 although they are decoded again at once.
13. Caption PNG states (~180 per video) are rendered on one thread (**~6 s**).
14. Re-rendering an edited script re-synthesises every voice line, even the unchanged ones.
15. SQLite runs in rollback-journal mode, so Studio reads block while the worker writes.

### Real-time / UX
16. The Studio polls every 1.5 s; logs and stage changes arrive late and in jumps.
17. Render progress jumps from 72 % to 92 % with nothing in between (the longest stage).
18. No ETA; no way to cancel a *running* job.
19. The command line shows log lines only, no live progress.

### Learning / predictions
20. `auto` style is a fixed random list; the channel's own view counts never steer it.
21. Nobody checks whether the Script Doctor's score actually predicts views.

### Server / reliability
22. Running the Studio on a server (`--host 0.0.0.0`) has no login at all.
23. Each Studio job builds its own `Studio`, so "YouTube refused uploads today" is forgotten between jobs.

## The plan

Each item shipped with tests. [x] = done.

### A. Accuracy and output quality
- [x] A1 Footage relevance: rank prior + metadata text match (slug/alt/tags) in candidate scoring.
- [x] A2 Fast pacing: split long scenes into sub-shots (`MAX_SHOT_SECONDS`, default 4.5) with distinct clips.
- [x] A3 Precise audio: separate audio pass with two-pass loudnorm (measure → linear apply) and gentle voice
      clean-up (`VOICE_ENHANCE`).
- [x] A4 Whisper: `WHISPER_MODEL` (auto picks a larger model on GPU), VAD for transcription, script text as
      the alignment prompt.
- [x] A5 Silence-anchored timing estimates (ffmpeg `silencedetect`) when no aligner is available.
- [x] A6 Script Doctor 2.0: rubric sub-scores with a weighted total, deterministic script lint fed into the
      review, optional extra rounds (`SCRIPT_REVIEW_ROUNDS`).
- [x] A7 Strict JSON-schema structured output for OpenAI-compatible providers that support it, with
      automatic downgrade.
- [x] A8 Best-frame cover: score candidate frames for sharpness, exposure and colour.
- [x] A9 Face-aware crop for clips (`--crop face`, optional OpenCV) with smooth tracking.
- [x] A10 Claude: default `claude-opus-5-5` (effort `high` unless set), fallbacks for Sonnet 5.5,
      truncation detection.

### B. Performance and real time
- [x] B1 Gradient backgrounds rendered small and scaled up; faster intermediates; parallel caption states.
- [x] B2 ffmpeg `-progress` parsing → smooth render percentage in Studio and CLI.
- [x] B3 Server-Sent Events stream for jobs and logs (polling stays as fallback).
- [x] B4 ETA from the stage timings of past jobs; cancel running jobs (kills ffmpeg).
- [x] B5 Voice line cache for re-renders; SQLite WAL + indexes.
- [x] B6 Live progress line in the terminal.

### C. Learning
- [x] C1 Style bandit: `auto` style uses Thompson sampling over the channel's views per format
      (with `LEARN_FROM_STATS`).
- [x] C2 Score calibration: Spearman correlation of retention score vs views, best formats and publish hours,
      in `stats` and the Studio Channel page.

### D. Server and reliability
- [x] D1 `STUDIO_PASSWORD` (HTTP Basic) for remote deployments.
- [x] D2 Shared YouTube-refusal state across Studio jobs.

### E. Docs
- [x] README, `.env.example`, CHANGELOG ("Unreleased"), measured before/after numbers.

## Results (measured on this machine, 19 Oct 2026)

| What | Before | After |
|---|---|---|
| Offline demo render, 1080×1920 facts video (median of 3, idle CPU, fonts cached) | 26.0 s (6 shots) | 15.5 s (12 shots) |
| Offline chat-story render (same conditions) | 27.1 s | 16.8 s |
| Generated background segment | ~10 s each | ~2.7 s each |
| Caption frames (≈180 states) | 5.9 s | 2.7 s |
| Final ffmpeg pass (same graph) | 13.9 s | 9.8 s |
| Phrase-boundary timing error, voice without timestamps (test with known pauses) | 0.24 s mean, 0.56 s max | 0.00 s |
| Loudness of a real edge-tts render (target −14 LUFS, −1.5 dBTP) | single-pass, dynamic | −14.0 LUFS, −1.5 dBFS peak |
| Retention score stored | the draft's, even when the rewrite was used | the used script's; a worse rewrite is dropped |
| Studio updates | polling every 1.5 s, no ETA, queued-only cancel | pushed instantly, % + time left, cancel running jobs |
| Real local LLM (Ollama ministral-3:8b), 20 s target | — | strict-schema replies accepted; draft 111 words → rewrite 71 words, re-graded 72/100 (rubric 7/8/6/9/5/9) |
| Tests | 128 | 174 |

Not measured here (no keys in this environment): stock-footage relevance on real Pexels/Pixabay results, and
OpenAI/Gemini strict-schema replies. Both are covered by unit tests with recorded API shapes and fall back to
the old behaviour when a provider refuses.

---

# Round 2 (20 Oct 2026): retention editing, story backgrounds, clip editing, reach

The repository passed 35 stars and 10 forks with no open issues, so this round goes by what people search
for and what competing tools advertise. A research pass covered MoneyPrinterTurbo, ShortGPT,
RedditVideoMakerBot, AI-Youtube-Shorts-Generator, OpenShorts and short-video-maker (READMEs, releases, issues
sorted by reactions), plus the commercial tools (Opus Clip, Submagic, Captions.ai, Revid, Faceless.video).
It also checked Google and YouTube autocomplete and where this repository ranks in GitHub search.

## What we found
- **Retention editing is now table stakes:** Submagic, Captions.ai and Opus Clip all lead with keyword
  emphasis in captions, auto zoom, silence and filler removal, and sound effects. We had none of the four.
- **Story formats need backgrounds:** the most-copied Reddit/chat-story look is a continuous gameplay or
  "satisfying" video under the story, often split-screen. RedditVideoMakerBot ships a background library.
  We only had per-scene picks from `media/`.
- **Clipping:** prompt-steered clipping ("find the funny bits about X") is a headline Opus feature and is
  easy with our transcript-reading picker. The per-clip score exists but is not shown as a "virality score"
  with reasons.
- **Reach:**
  - `pip install purffle-shorts` returns 404, because the 3.0.0 PyPI publish failed: no trusted publisher
    is configured on PyPI.
  - There is no Colab notebook, which competitors have.
  - The Studio's REST API is undocumented, while n8n-style automation is a common search.
  - The repository description lacks plain-word phrases that GitHub search matches ("Opus Clip
    alternative", "YouTube automation"), and there is no custom social preview.
- **Bug found:** none new. Tag lengths, title limits and upload retries were already handled.

## Plan
### F. Retention editing
- [x] F1 Sound effects synthesised in code (no files to license): whoosh on scene changes, pop per text
      message, low hit under the hook. Placed 11 dB under the measured voice whichever TTS engine spoke
      (`SOUND_EFFECTS`, `SFX_VOLUME`).
- [x] F2 Keyword emphasis: the LLM marks 1–2 key words per scene (strict schema), and numbers are always
      emphasised. Drawn in a per-style colour by both the Pillow and libass renderers (`CAPTION_EMPHASIS`).
- [x] F4 An emoji per scene (strict-schema field), Twemoji images cached in data/emoji and credited in the
      description. A colour-emoji font was tried first: the Google Fonts build is COLR/SVG, which Pillow's
      FreeType can't draw, and the bitmap build is no longer published at a stable URL.
- [x] F3 Background video for stories (`BACKGROUND_VIDEO` file/folder/URL, `--background`): one continuous
      random stretch, either as the picture (`full`) or under the footage (`split`, footage searched in
      the top half's shape).

### G. Clip editing
- [x] G1 Jump cuts: pauses over `CLIP_MAX_PAUSE` shortened and "um/uh" cut. Cuts land on frame
      boundaries and audio is split into frame-sized packets, so picture and sound are cut at the same
      instants (no drift).
- [x] G2 Punch-in zoom between sentences (piecewise-constant zoompan, `CLIP_ZOOM`).
- [x] G3 `clip --prompt "…"` steers which moments are picked.
- [x] G4 Virality score with reasons shown for clips in CLI and Studio.

### H. Reach and SEO
- [x] H1 YouTube autocomplete as a topic source (`TOPIC_SOURCES=search`) and as real search phrases handed
      to the script writer for titles and tags (`SEO_KEYWORDS`).
- [x] H2 Localised YouTube titles and descriptions (`LOCALIZE_METADATA=es,pt,hi`), so viewers in other
      languages see them in their own language.
- [x] H3 Optional caption-track upload (`UPLOAD_CAPTIONS`), with a graceful skip when the token lacks the
      scope.
- [x] H4 Colab notebook, documented REST API with an n8n example, docker-compose.
- [x] H5 README rewritten around search phrases, with headings people search for.

### J. TikTok and Instagram (added on 20 Oct 2026 after the first QA pass)
- [x] J1 `PUBLISH_TO=youtube,tiktok,instagram,…`. TikTok and five more networks go through the Upload-Post
      relay: TikTok's own Content Posting API only lets audited apps publish public videos, and every user
      would need their own audited app. Instagram can instead use its official API with a resumable upload
      straight from this computer (Graph API v25.0, available until July 2028).
- [x] J2 Per-network captions (no `#shorts`, cut to each network's length) and the same publish slot as YouTube
      (Upload-Post `scheduled_date`; Instagram's API posts at once). Each result goes in `metadata.json`;
      retries re-send only what failed and never upload to YouTube twice; the MP4 is kept until every
      destination has it.
- [x] J3 CLI `--publish-to`, Studio *Publish when done* and per-network chips with *Publish the rest*, MCP
      `upload_video` results, `doctor` checks, and README, `.env.example` and CHANGELOG notes. Tested against
      recorded API responses; live endpoints checked with invalid credentials only (Upload-Post answers 401
      "Invalid API key", Graph v25.0 answers OAuthException 190), because no real accounts were available.

### I. QA
- [x] Unit tests for every item, then full CLI, Studio (browser), MCP and offline end-to-end renders of
      every format, layout and clip option. A real local-LLM run where time allows.

Not doing this round:
- **TikTok and Instagram posting.** TikTok's API posts private-only until an app audit, Instagram needs
  a public video URL, and the alternative is a paid relay. None of these can be tested here.
- **Voice cloning.** Its dependencies are heavy and GPU-bound.
- **AI video generation.** It needs paid APIs.

## Round 2 results (measured on this machine, 20 Oct 2026)

| What | Result |
|---|---|
| Tests | 174 → 232 (with TikTok and Instagram), all passing, ruff clean, `node --check` clean, wheel and sdist pass `twine check --strict` |
| Clean install | Wheel installed with `[clip,face]` into a fresh Python 3.10 venv; every CLI command run as a new user |
| Render matrix (installed wheel) | 16/16 rendered: 4 demo formats; 16:9, 1:1 and 4:5; full and split gameplay background; no-effects neon; Hindi; all 5 example scripts. Every file at its expected size, −14.0 LUFS (±0.1), −1.5 dBFS peak |
| Jump-cut sync | Flash-and-beep test video: after removing ~6 s of pauses, every flash and its beep are within one frame. Speech test: 32.6 s → 17.5 s, "um" and "uh" removed |
| Sound-effect level | 11 dB under the voice measured after the voice chain (test within ±1 dB), whatever the voice's own loudness |
| MCP over stdio | initialize, tools/list, make_short (Reddit story, split background), clip_video (with a brief), list_videos, an unknown tool: all correct |
| Studio in a browser | New Create controls (background, layout, effects, key words, emoji) and Clip controls (brief, jump cuts, zoom) work. A split-layout render and a two-clip job finished with the expected log; no horizontal scroll at 375 px; requests while the server is down fell from ~30 to 5 per 25 s |
| Colab notebook | Cells 1, 2, 3, 5 and 6 run with nbclient on this machine (cell 4 needs an LLM) |
| Live YouTube search suggestions | Topic questions for 5 niches checked by hand; filters for off-topic, sensitive and adult phrases tuned on them |

**Bugs found by this QA and fixed:**
- faster-whisper 1.2.1 crashed with the current PyAV.
- Background videos were also used as scene footage.
- The CLI had no `--source search`.
- A Studio API request could upload despite `UPLOAD=false`.
- A dead server was polled every 1.5 s indefinitely.
- Offline clip titles kept a leading "uh".
- The planner, with a small model, produced an invented health claim.

**Not verified here:**
- **A full make with a real LLM.** The local Ollama was serving another project and timed out after 600 s, and later stopped running. The failure path was verified: a clear error, exit 1, and the idea returned to the queue. The live YouTube search step worked on the same run. The script, review, keyword and localisation prompts are covered with recorded fakes, and round 1 ran the full pipeline on this Ollama.
- **Real YouTube uploads with localizations and caption tracks.** The API calls are tested against fakes of the client library.
- **The Colab notebook on Google's machines.** It needs the branch merged into `main` first.
