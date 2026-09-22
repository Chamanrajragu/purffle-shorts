"""The production line: topic -> script -> voice -> footage -> captions -> render -> upload."""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from . import ffmpeg, tts, youtube
from .config import Settings
from .history import History, now_iso
from .llm import LLM, LLMConfigError
from .media import Visuals
from .overlays import build_overlays
from .render import extract_frame, render_video
from .script import Script, load_script, write_script
from .timing import caption_chunks, scene_timeline, srt
from .topics import Topic, pick_topic
from .utils import redact, slugify, truncate_words

log = logging.getLogger("purffle")

END_PAD = 0.6          # seconds of breathing room after the last word
REUSABLE_SOURCES = {"generated", "local", "openai-images", "ai", "dalle", "gpt-image", "pollinations"}


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


def final_title(script: Script) -> str:
    t = script.title
    return f"{t} #shorts" if len(t) + 8 <= 100 else truncate_words(t, 100)


def final_description(script: Script, credits: set[str], settings: Settings) -> str:
    parts = [script.description.strip()] if script.description.strip() else []
    parts.append(" ".join(script.hashtags))
    if settings.credit_footage and credits:
        parts.append("Footage: " + ", ".join(sorted(credits)))
    return "\n\n".join(p for p in parts if p)


class Studio:
    def __init__(self, settings: Settings):
        self.s = settings
        self.history = History(settings.data_path / "history.db")
        self._llm: LLM | None = None

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
    def _speak(self, text: str, work: Path) -> tts.Speech:
        engines = [self.s.tts_engine]
        if self.s.tts_engine != "edge":
            engines.append("edge")
        if self.s.offline:
            engines += ["system", "silent"]
        last: Exception | None = None
        for eng in dict.fromkeys(engines):
            try:
                cfg = self.s if eng == self.s.tts_engine else replace(self.s, tts_engine=eng, tts_voice="")
                return tts.synthesize(text, work, cfg)
            except Exception as e:
                last = e
                log.warning("Voice engine '%s' failed: %s", eng, e)
        raise RuntimeError(f"All voice engines failed: {last}")

    # ------------------------------------------------------------------ one video
    def make(self, topic: str | None = None, *, source: str | None = None, upload: bool | None = None,
             style: str | None = None, script_file: str | Path | None = None) -> Result:
        t0 = time.time()
        s = self.s
        upload = s.upload if upload is None else upload
        folder = None
        try:
            if script_file:  # your own (or an edited) script: no topic picking, no LLM call
                script = load_script(script_file, s)
                pick = Topic(script.topic, "script")
                writer = "script file"
                log.info("Script from %s (%d scenes): %s", script_file, len(script.scenes), script.title)
            else:
                pick = pick_topic(s, self.history, explicit=topic, source=source)
                log.info("Topic [%s]: %s", pick.source, pick.subject)
                script = write_script(self.llm, pick.subject, s, source=pick.source,
                                      avoid=self.history.recent_titles(), context=pick.context, style=style)
                writer = self.llm.label if self.llm else "offline"

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            folder = (s.out_path / f"{stamp}_{slugify(script.title)}").resolve()  # absolute: history outlives cwd
            work = folder / "work"
            work.mkdir(parents=True, exist_ok=True)
            (folder / "script.json").write_text(json.dumps(script.to_dict(), indent=2, ensure_ascii=False))

            speech = self._speak(script.narration, work)
            total = round(speech.duration + END_PAD, 3)
            timeline = scene_timeline([sc.narration for sc in script.scenes], speech.words, total, s.language)
            T = s.transition_seconds if s.transition != "none" else 0.0
            jobs = [(script.scenes[st.index].search_query, script.scenes[st.index].image_prompt, st.duration + T)
                    for st in timeline]
            visuals = Visuals(s, self.history.used_media())
            media = visuals.for_scenes(jobs, script.topic, work / "media")

            chunks = caption_chunks(speech.words, s.caption_max_words, total=total)
            plan = build_overlays(s, chunks, total, script.hook_text, work)
            video = folder / "short.mp4"
            render_video(s, media, [st.duration for st in timeline], speech.audio, total, plan, video, work)

            info = ffmpeg.probe(video)
            if (info["width"], info["height"]) != s.resolution or abs(info["duration"] - total) > 0.5:
                raise RuntimeError(f"Render check failed: got {info['width']}x{info['height']} "
                                   f"{info['duration']:.2f}s, expected {s.width}x{s.height} {total:.2f}s")
            extract_frame(video, min(1.2, total / 3), folder / "cover.jpg")
            (folder / "captions.srt").write_text(srt(chunks), encoding="utf-8")

            title = final_title(script)
            description = final_description(script, visuals.credits, s)
            meta = {
                "title": title, "description": description, "tags": script.tags,
                "category_id": script.category_id, "language": s.language,
                "topic": script.topic, "source": pick.source, "style": script.style,
                "duration": round(info["duration"], 2), "resolution": f"{s.width}x{s.height}",
                "llm": writer,
                "voice": f"{speech.engine}:{speech.voice}", "timing": speech.timing,
                "visuals": [{"source": m.source, "id": m.id, "kind": m.kind, "query": m.query} for m in media],
                "created_at": now_iso(),
            }
            (folder / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

            rid = self.history.add_video(
                subject=pick.subject, source=pick.source, topic=script.topic, style=script.style,
                language=s.language, title=title, description=description, tags=script.tags,
                folder=str(folder), video_path=str(video), duration=info["duration"],
                llm=meta["llm"], voice=meta["voice"], status="rendered")
            self.history.mark_media([m.key for m in media if m.source not in REUSABLE_SOURCES])
            if pick.key:
                self.history.mark_topic(pick.key)
            if not os.getenv("KEEP_WORK"):
                shutil.rmtree(work, ignore_errors=True)

            took = time.time() - t0
            log.info("Rendered %s (%.1fs video) in %.0fs -> %s", title, info["duration"], took, video)
            result = Result(True, title, folder, video, "rendered", seconds=took, record_id=rid)
            if upload:
                self.upload_record(rid, result)
            return result
        except (youtube.NotAuthorized, LLMConfigError, KeyboardInterrupt):
            raise  # setup problems stop the run instead of failing every video the same way
        except Exception as e:
            log.error("Video failed: %s", redact(e), exc_info=log.isEnabledFor(logging.DEBUG))
            return Result(False, folder=folder, status="failed", error=redact(e), seconds=time.time() - t0)

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
