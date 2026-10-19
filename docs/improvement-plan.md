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
