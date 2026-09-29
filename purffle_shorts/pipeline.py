"""The production line: topic -> script -> review -> voice -> footage -> captions -> render -> upload.

``Studio.draft`` stops after the script (so it can be read and edited first); ``Studio.make`` runs the
whole line, optionally followed by translated copies that reuse the same footage."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from . import analytics, ffmpeg, notify, topics, tts, youtube
from .config import Settings
from .history import History, now_iso
from .llm import LLM, LLMConfigError
from .media import MediaItem, Visuals
from .overlays import ChatMessage, build_overlays
from .render import extract_frame, render_video
from .script import MULTI_SPEAKER, Script, load_script, review_script, translate_script, write_script
from .timing import caption_chunks, scene_timeline, srt
from .topics import Topic, pick_topic
from .utils import redact, slugify, truncate_words

log = logging.getLogger("purffle")

END_PAD = 0.6          # seconds of breathing room after the last word
REUSABLE_SOURCES = {"generated", "local", "openai-images", "ai", "dalle", "gpt-image", "pollinations"}

# Rough share of the work done when each stage starts (for progress bars).
STAGES = {"topic": 2, "script": 8, "review": 20, "voice": 32, "footage": 45, "captions": 62, "render": 72,
          "check": 92, "upload": 95, "translate": 97, "done": 100}

ProgressFn = Callable[[str, int, str], None]


@dataclass
class Result:
    ok: bool
    title: str = ""
    folder: Path | None = None
    video: Path | None = None
    status: str = ""
    youtube_id: str | None = None
    publish_at: str | None = None
    seconds: float = 0.0
    error: str = ""
    record_id: int | None = None
    score: int | None = None
    language: str = ""
    variants: list[Result] = field(default_factory=list)


def quota_day_start() -> str:
    """YouTube's daily quota resets at midnight Pacific time."""
    from zoneinfo import ZoneInfo
    pt = datetime.now(ZoneInfo("America/Los_Angeles"))
    start = pt.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).isoformat(timespec="seconds")


def seconds_until_quota_reset() -> float:
    from zoneinfo import ZoneInfo
    pt = datetime.now(ZoneInfo("America/Los_Angeles"))
    nxt = (pt.replace(hour=0, minute=0, second=0, microsecond=0)).timestamp() + 86400
    return max(60.0, nxt - pt.timestamp() + 120)


def final_title(script: Script, settings: Settings | None = None) -> str:
    t = script.title
    if settings is not None and not settings.vertical:
        return truncate_words(t, 100)  # a 16:9 video is not a Short
    return f"{t} #shorts" if len(t) + 8 <= 100 else truncate_words(t, 100)


def final_description(script: Script, credits: set[str], settings: Settings) -> str:
    parts = [script.description.strip()] if script.description.strip() else []
    tags = script.hashtags if settings.vertical else [h for h in script.hashtags if h.lower() != "#shorts"]
    parts.append(" ".join(tags))
    if settings.credit_footage and credits:
        parts.append("Footage: " + ", ".join(sorted(credits)))
    return "\n\n".join(p for p in parts if p)


def _unique_folder(root: Path, name: str) -> Path:
    folder = root / name
    n = 2
    while folder.exists():
        folder = root / f"{name}-{n}"
        n += 1
    return folder


def _media_for(timeline, media_map: dict[int, MediaItem]) -> list[MediaItem]:
    """Reuse the original video's footage for a translated copy (its scenes may merge differently)."""
    keys = sorted(media_map)
    out = []
    for st in timeline:
        k = max([k for k in keys if k <= st.index], default=keys[0])
        out.append(media_map[k])
    return out


class Studio:
    def __init__(self, settings: Settings, progress: ProgressFn | None = None):
        self.s = settings
        self.history = History(settings.data_path / "history.db")
        self._llm: LLM | None = None
        self.progress = progress
        self._stats_synced = 0.0

    def _step(self, stage: str, message: str = "") -> None:
        if self.progress:
            try:
                self.progress(stage, STAGES.get(stage, 0), message)
            except Exception:  # a progress display must never break a video
                log.debug("progress callback failed", exc_info=True)

    @property
    def llm(self) -> LLM | None:
        if self.s.offline:
            return None
        if self._llm is None:
            self._llm = LLM(self.s)
            log.info("LLM: %s%s", self._llm.label,
                     f" (fallbacks: {', '.join(str(p) for p in self._llm.providers[1:])})"
                     if len(self._llm.providers) > 1 else "")
        return self._llm

    # ------------------------------------------------------------------ voice with fallbacks
    def _speak(self, script: Script, work: Path, s: Settings) -> tts.Speech:
        engines = [s.tts_engine]
        if s.tts_engine != "edge":
            engines.append("edge")
        if s.offline:
            engines += ["system", "silent"]
        lines = [(sc.speaker, sc.narration) for sc in script.scenes] if (
            script.multi_speaker or script.style in MULTI_SPEAKER) else None
        last: Exception | None = None
        for eng in dict.fromkeys(engines):
            try:
                cfg = s if eng == s.tts_engine else replace(s, tts_engine=eng, tts_voice="", tts_voice_b="")
                if lines:
                    return tts.synthesize_lines(lines, work / "voice", cfg)
                return tts.synthesize(script.narration, work, cfg)
            except Exception as e:
                last = e
                log.warning("Voice engine '%s' failed: %s", eng, e)
        raise RuntimeError(f"All voice engines failed: {last}")

    # ------------------------------------------------------------------ script only
    def draft(self, topic: str | None = None, *, source: str | None = None, style: str | None = None,
              url: str | None = None, document: str | Path | None = None) -> tuple[Script, Topic, str]:
        """Pick a topic, write the script and let the Script Doctor improve it. Nothing is rendered."""
        s = self.s
        self._step("topic")
        if url:
            pick = topics.from_url(url)
        elif document:
            pick = topics.from_document(document)
        else:
            pick = pick_topic(s, self.history, explicit=topic, source=source)
        if topic and (url or document):
            pick.subject = f"{topic} (source: {pick.subject})"
        log.info("Topic [%s]: %s", pick.source, pick.subject)
        try:
            self._step("script", pick.subject)
            insights = analytics.insights(self.history) if s.learn_from_stats else ""
            script = write_script(self.llm, pick.subject, s, source=pick.source, avoid=self.history.recent_titles(),
                                  context=pick.context, style=style or pick.style or None, insights=insights)
            if self.llm is not None and s.script_review != "off":
                self._step("review", "Script Doctor")
                script = review_script(self.llm, script, s)
        except BaseException:
            if pick.idea_id:
                self.history.release_idea(pick.idea_id)
            raise
        return script, pick, self.llm.label if self.llm else "offline"

    # ------------------------------------------------------------------ one video
    def make(self, topic: str | None = None, *, source: str | None = None, upload: bool | None = None,
             style: str | None = None, script_file: str | Path | None = None, script: Script | None = None,
             url: str | None = None, document: str | Path | None = None,
             languages: list[str] | None = None) -> Result:
        t0 = time.time()
        s = self.s
        upload = s.upload if upload is None else upload
        languages = s.also_languages if languages is None else languages
        state: dict = {}
        pick: Topic | None = None
        try:
            if script is not None or script_file:
                if script is None:
                    script = load_script(script_file, s)
                pick, writer = Topic(script.topic, "script"), ("script file" if script_file else "editor")
                log.info("Script from %s (%d scenes): %s", script_file or "editor", len(script.scenes), script.title)
            else:
                script, pick, writer = self.draft(topic, source=source, style=style, url=url, document=document)
            return self.produce(script, pick, writer, upload=upload, t0=t0, languages=languages, state=state)
        except (youtube.NotAuthorized, LLMConfigError, KeyboardInterrupt):
            raise  # setup problems stop the run instead of failing every video the same way
        except Exception as e:
            if pick is not None and pick.idea_id and not state.get("record_id"):
                self.history.release_idea(pick.idea_id)
            log.error("Video failed: %s", redact(e), exc_info=log.isEnabledFor(logging.DEBUG))
            notify.send(s, "failed", title=getattr(script, "title", "") or (pick.subject if pick else ""),
                        detail=redact(e))
            return Result(False, folder=state.get("folder"), status="failed", error=redact(e),
                          seconds=time.time() - t0)

    def produce(self, script: Script, pick: Topic, writer: str, *, upload: bool, t0: float | None = None,
                languages: list[str] | None = None, media_map: dict[int, MediaItem] | None = None,
                credits: set[str] | None = None, parent_id: int | None = None, settings: Settings | None = None,
                state: dict | None = None) -> Result:
        t0 = t0 or time.time()
        state = state if state is not None else {}
        s = settings or self.s
        if script.language and script.language != s.language:
            s = replace(s, language=script.language, tts_voice="", tts_voice_b="")

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{stamp}_{slugify(script.title)}" + (f"-{s.language}" if parent_id else "")
        folder = _unique_folder(s.out_path, name).resolve()  # absolute: history outlives cwd
        state["folder"] = folder
        work = folder / "work"
        work.mkdir(parents=True, exist_ok=True)
        (folder / "script.json").write_text(json.dumps(script.to_dict(), indent=2, ensure_ascii=False))
        try:
            self._step("voice", f"{s.tts_engine} voice")
            speech = self._speak(script, work, s)
            total = round(speech.duration + END_PAD, 3)
            chat = script.style == "chat"
            timeline = scene_timeline([sc.narration for sc in script.scenes], speech.words, total, s.language,
                                      starts=speech.line_starts, min_len=4.5 if chat else 1.2)
            T = s.transition_seconds if s.transition != "none" else 0.0

            self._step("footage", f"{len(timeline)} scenes")
            if media_map:
                media = _media_for(timeline, media_map)
                credits = set(credits or ())
            else:
                jobs = [(script.scenes[st.index].search_query, script.scenes[st.index].image_prompt,
                         st.duration + T) for st in timeline]
                visuals = Visuals(s, self.history.used_media())
                media = visuals.for_scenes(jobs, script.topic, work / "media")
                credits = visuals.credits
            by_scene = {st.index: m for st, m in zip(timeline, media)}

            self._step("captions")
            chunks = caption_chunks(speech.words, s.caption_max_words, total=total)
            labels = ({"A": script.speaker_name("A"), "B": script.speaker_name("B")}
                      if script.style == "dialogue" and script.multi_speaker else None)
            messages = ([ChatMessage(sc.speaker, sc.narration, st) for sc, st in zip(script.scenes, speech.line_starts)]
                        if chat and speech.line_starts else None)
            plan = build_overlays(s, chunks, total, script.hook_text, work, labels=labels, chat=messages,
                                  contact=script.speaker_name("A"))

            self._step("render", f"{s.width}x{s.height}")
            video = folder / ("short.mp4" if s.vertical else "video.mp4")
            render_video(s, media, [st.duration for st in timeline], speech.audio, total, plan, video, work)

            self._step("check")
            info = ffmpeg.probe(video)
            if (info["width"], info["height"]) != s.resolution or abs(info["duration"] - total) > 0.5:
                raise RuntimeError(f"Render check failed: got {info['width']}x{info['height']} "
                                   f"{info['duration']:.2f}s, expected {s.width}x{s.height} {total:.2f}s")
            extract_frame(video, min(1.2, total / 3), folder / "cover.jpg")
            (folder / "captions.srt").write_text(srt(chunks), encoding="utf-8")

            title = final_title(script, s)
            description = final_description(script, credits, s)
            meta = {
                "title": title, "description": description, "tags": script.tags,
                "category_id": script.category_id, "language": s.language,
                "topic": script.topic, "source": pick.source, "style": script.style,
                "duration": round(info["duration"], 2), "resolution": f"{s.width}x{s.height}",
                "llm": writer, "score": script.score, "review": script.review, "cast": script.cast,
                "voice": f"{speech.engine}:{speech.voice}", "timing": speech.timing,
                "visuals": [{"source": m.source, "id": m.id, "kind": m.kind, "query": m.query} for m in media],
                "parent_id": parent_id, "created_at": now_iso(),
            }
            (folder / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

            rid = self.history.add_video(
                subject=pick.subject, source=pick.source, topic=script.topic, style=script.style,
                language=s.language, title=title, description=description, tags=script.tags,
                folder=str(folder), video_path=str(video), duration=info["duration"],
                llm=meta["llm"], voice=meta["voice"], status="rendered", score=script.score, parent_id=parent_id)
            state["record_id"] = rid
            if not media_map:
                self.history.mark_media([m.key for m in media if m.source not in REUSABLE_SOURCES])
            if pick.key and not parent_id:
                self.history.mark_topic(pick.key)
            if pick.idea_id and not parent_id:
                self.history.link_idea(pick.idea_id, rid)

            took = time.time() - t0
            log.info("Rendered %s (%.1fs video) in %.0fs -> %s", title, info["duration"], took, video)
            result = Result(True, title, folder, video, "rendered", seconds=took, record_id=rid,
                            score=script.score, language=s.language)
            if upload:
                self._step("upload")
                self.upload_record(rid, result)
            else:
                notify.send(s, "rendered", title=title, detail=str(video))

            for lang in [x for x in dict.fromkeys(languages or []) if x != s.language]:
                self._step("translate", lang)
                result.variants.append(self._translation(script, pick, writer, lang, s, by_scene, credits,
                                                         rid, upload))
            self._step("done", title)
            return result
        finally:
            if not os.getenv("KEEP_WORK"):
                shutil.rmtree(work, ignore_errors=True)

    def _translation(self, script: Script, pick: Topic, writer: str, lang: str, s: Settings,
                     by_scene: dict[int, MediaItem], credits: set[str], parent_id: int, upload: bool) -> Result:
        t0 = time.time()
        try:
            if self.llm is None:
                raise RuntimeError("translations need an LLM (not available in demo mode)")
            translated = translate_script(self.llm, script, lang)
            translated.score, translated.review = script.score, script.review
            log.info("Translated to %s: %s", lang, translated.title)
            return self.produce(translated, pick, writer, upload=upload, t0=t0, media_map=by_scene, credits=credits,
                                parent_id=parent_id, settings=replace(s, language=lang, tts_voice="", tts_voice_b=""))
        except youtube.NotAuthorized:
            raise
        except Exception as e:  # including LLMConfigError: the original video is already made
            log.error("Translation to %s failed: %s", lang, redact(e))
            return Result(False, status="failed", error=redact(e), language=lang, seconds=time.time() - t0)

    # ------------------------------------------------------------------ uploading
    def quota_left(self) -> int:
        return self.s.daily_upload_limit - self.history.uploads_since(quota_day_start())

    def upload_record(self, rid: int, result: Result | None = None) -> str:
        rec = self.history.get(rid)
        if not rec or not rec.get("video_path") or not Path(rec["video_path"]).exists():
            log.error("Video #%s has no file to upload", rid)
            return "missing"
        if self.quota_left() <= 0:
            log.warning("Daily upload limit (%d) reached — video #%d queued for tomorrow", self.s.daily_upload_limit, rid)
            self.history.update_video(rid, status="queued")
            if result:
                result.status = "queued"
            notify.send(self.s, "queued", title=rec["title"], detail="daily upload limit reached")
            return "queued"
        folder = Path(rec["folder"])
        meta = json.loads((folder / "metadata.json").read_text()) if (folder / "metadata.json").exists() else {}
        publish = youtube.next_publish_slot(self.s, self.history.scheduled_times())
        body = youtube.build_body(self.s, rec["title"], rec["description"] or "",
                                  json.loads(rec["tags"] or "[]"), meta.get("category_id", "27"),
                                  meta.get("language", self.s.language), publish)
        try:
            resp = youtube.upload(self.s, Path(rec["video_path"]), body)
        except youtube.QuotaExceeded:
            log.warning("YouTube quota exhausted — video #%d queued", rid)
            self.history.update_video(rid, status="queued")
            if result:
                result.status = "queued"
            return "queued"
        except youtube.NotAuthorized:
            raise
        except Exception as e:
            log.error("Upload of #%d failed: %s", rid, e)
            self.history.update_video(rid, status="failed", error=str(e)[:500])
            if result:
                result.status, result.error = "upload-failed", str(e)
            notify.send(self.s, "failed", title=rec["title"], detail=f"upload failed: {redact(e)}")
            return "failed"
        vid = resp.get("id")
        status = "scheduled" if publish else "uploaded"
        publish_iso = youtube.to_rfc3339(publish) if publish else None
        fields = dict(status=status, youtube_id=vid, uploaded_at=now_iso(), publish_at=publish_iso, error=None)
        if not self.s.keep_videos:
            Path(rec["video_path"]).unlink(missing_ok=True)
            fields["video_path"] = None
        self.history.update_video(rid, **fields)
        when = f", goes public {publish.strftime('%a %d %b %H:%M %Z')}" if publish else ""
        log.info("%s: https://youtube.com/shorts/%s%s", status.capitalize(), vid, when)
        notify.send(self.s, status, title=rec["title"], url=f"https://youtube.com/shorts/{vid}",
                    detail=f"public {publish.strftime('%a %d %b %H:%M %Z')}" if publish else "")
        if result:
            result.status, result.youtube_id, result.publish_at = status, vid, publish_iso
        return status

    def flush_queue(self, include_rendered: bool = False) -> int:
        statuses = ("queued", "rendered") if include_rendered else ("queued",)
        done = 0
        for rec in self.history.pending_uploads(statuses):
            if self.quota_left() <= 0:
                break
            if self.upload_record(rec["id"]) in ("uploaded", "scheduled"):
                done += 1
        return done

    def delete(self, rid: int) -> bool:
        """Remove a video from the library and delete its folder (never touches YouTube)."""
        rec = self.history.get(rid)
        if not rec:
            return False
        folder = Path(rec["folder"]) if rec.get("folder") else None
        if folder and folder.is_dir() and folder.resolve().is_relative_to(self.s.out_path.resolve()):
            shutil.rmtree(folder, ignore_errors=True)
        self.history.delete_video(rid)
        return True

    # ------------------------------------------------------------------ autopilot
    def autopilot(self, *, count: int | None = None, once: bool = False, upload: bool | None = None,
                  topic: str | None = None, source: str | None = None) -> int:
        s = self.s
        upload = s.upload if upload is None else upload
        produced, batch, empty_batches = 0, 0, 0
        mode = "upload" if upload else "no-upload"
        _ = self.llm  # fail fast on LLM configuration problems
        log.info("Autopilot started (%s, batch %d, workers %d%s)", mode, s.batch_size, s.workers,
                 f", target {count}" if count else "")
        try:
            while True:
                batch += 1
                if s.learn_from_stats and time.time() - self._stats_synced > 12 * 3600:
                    analytics.sync_stats(s, self.history)
                    self._stats_synced = time.time()
                if upload:
                    self.flush_queue()
                    if self.quota_left() <= 0 and self.history.pending_uploads():
                        wait = seconds_until_quota_reset()
                        log.info("Upload limit reached and videos are queued; sleeping %.1fh until quota resets",
                                 wait / 3600)
                        time.sleep(wait)
                        continue
                n = s.batch_size if count is None else min(s.batch_size, count - produced)
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(s.workers, n)) as ex:
                    futs = [ex.submit(self.make, topic, source=source, upload=upload) for _ in range(n)]
                    results = [f.result() for f in futs]
                ok = sum(r.ok for r in results)
                produced += ok
                log.info("Batch %d: %d/%d succeeded (total %d)", batch, ok, n, produced)
                empty_batches = empty_batches + 1 if ok == 0 else 0
                if once or (count is not None and produced >= count):
                    break
                if empty_batches >= 3:
                    log.error("Three batches in a row produced nothing — stopping. Check the log above.")
                    break
                if s.batch_delay:
                    log.info("Next batch in %ds", s.batch_delay)
                    time.sleep(s.batch_delay)
        except KeyboardInterrupt:
            log.info("Stopped by user.")
        return produced
