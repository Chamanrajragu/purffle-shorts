"""PurffleShorts Studio — a local web app (standard library only, no build step).

    purffle-shorts studio        -> http://127.0.0.1:8765

Create videos (or draft and edit the script first), watch every stage live, browse and play the library,
plan ideas, clip long videos, read channel stats and check the setup. It binds to localhost, refuses
requests addressed to any other host name (DNS rebinding), and every write needs a per-session token,
so other websites can't drive it from your browser.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import mimetypes
import os
import queue
import re
import secrets
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field, fields, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .config import ASPECTS, Settings, aspect_resolution

log = logging.getLogger("purffle")

WEB = Path(__file__).parent / "web"
FILES = ("short.mp4", "video.mp4", "cover.jpg", "captions.srt", "metadata.json", "script.json")
STATIC = {"app.js": "text/javascript; charset=utf-8", "app.css": "text/css; charset=utf-8",
          "icon.svg": "image/svg+xml", "icon.png": "image/png"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
LOCAL_KINDS = {"pull", "prefetch", "bench"}   # Local AI jobs: run on their own worker


@dataclass
class Job:
    id: int
    kind: str                       # make | draft | clip | plan | upload | stats
    params: dict
    label: str = ""
    status: str = "queued"          # queued | running | done | failed | cancelled
    stage: str = ""
    pct: int = 0
    message: str = ""
    log: list[str] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    eta_fn: object = field(default=None, repr=False)   # the running Studio's eta(), while it runs
    stop: threading.Event = field(default_factory=threading.Event, repr=False)  # cancel for side jobs

    def public(self, full_log: bool = False) -> dict:
        eta = None
        if self.status == "running" and callable(self.eta_fn):
            try:
                eta = self.eta_fn()
            except Exception:
                eta = None
        return {"id": self.id, "kind": self.kind, "label": self.label, "status": self.status, "stage": self.stage,
                "pct": self.pct, "message": self.message, "result": self.result, "created": self.created,
                "started": self.started, "finished": self.finished, "eta": eta,
                "log": self.log if full_log else self.log[-60:]}


class _JobLog(logging.Handler):
    """Copies log lines produced by the worker thread into the running job."""

    def __init__(self, studio: StudioServer):
        super().__init__(logging.INFO)
        self.studio = studio
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        # Local AI jobs run on their own named threads; everything else belongs to the one video job.
        job = self.studio.lanes.get(record.threadName)
        if job is None and (record.threadName == "studio-worker" or record.threadName.startswith("ThreadPoolExecutor")):
            job = self.studio.current
        if job is None:
            return
        job.log.append(self.format(record))
        del job.log[:-400]
        self.studio.changed()


def _choice(value, allowed, default=None):
    return value if value in allowed else default


class StudioServer:
    def __init__(self, settings: Settings):
        from .pipeline import Studio
        self.settings = settings
        self.studio = Studio(settings)
        # values that came from the command line, not .env: a save on the Settings page must not undo them
        try:
            base = Settings.from_env()
            self._pinned = {f.name: getattr(settings, f.name) for f in fields(Settings)
                            if getattr(settings, f.name) != getattr(base, f.name)}
        except Exception:
            self._pinned = {}
        # STUDIO_TOKEN fixes the write token, so scripts and tools like n8n can call the API (see docs/api.md)
        self.token = os.getenv("STUDIO_TOKEN", "").strip() or secrets.token_urlsafe(24)
        self.jobs: dict[int, Job] = {}
        self.queue: queue.Queue[Job] = queue.Queue()
        # Local AI jobs never block a video, and a speed test never waits behind a 5 GB download
        self.side: dict[str, queue.Queue[Job]] = {"pull": queue.Queue(), "quick": queue.Queue()}
        self.current: Job | None = None
        self.lanes: dict[str, Job] = {}       # Local AI thread name -> the job it is running
        self._next = 1
        self._lock = threading.Lock()
        self._voices: dict[str, list] = {}
        self.version = 0                       # bumped on every job change; the event stream waits on it
        self._changed = threading.Condition()
        logging.getLogger().addHandler(_JobLog(self))
        threading.Thread(target=self._worker, name="studio-worker", daemon=True).start()
        for lane in self.side:
            threading.Thread(target=self._side_worker, args=(lane,), name=f"studio-{lane}", daemon=True).start()
        self._ap_lock = threading.Lock()
        threading.Thread(target=self._autopilot_loop, name="studio-autopilot", daemon=True).start()
        if settings.check_updates:
            threading.Thread(target=self._update_loop, name="studio-updates", daemon=True).start()

    def changed(self) -> None:
        with self._changed:
            self.version += 1
            self._changed.notify_all()

    def wait_change(self, seen: int, timeout: float) -> int:
        with self._changed:
            self._changed.wait_for(lambda: self.version != seen, timeout=timeout)
            return self.version

    def jobs_public(self) -> list[dict]:
        return [j.public() for j in sorted(self.jobs.values(), key=lambda j: j.id, reverse=True)[:40]]

    # ------------------------------------------------------------------ jobs
    def submit(self, kind: str, params: dict, label: str = "") -> Job:
        with self._lock:
            job = Job(self._next, kind, params, label=label or kind)
            self._next += 1
            self.jobs[job.id] = job
            for old in sorted(self.jobs)[:-100]:  # keep the list bounded
                if self.jobs[old].status not in ("queued", "running"):
                    del self.jobs[old]
        if kind in LOCAL_KINDS:
            self.side["pull" if kind == "pull" else "quick"].put(job)
        else:
            self.queue.put(job)
        self.changed()
        return job

    # ------------------------------------------------------------------ autopilot
    def busy(self) -> bool:
        """Is a video-making job waiting or running? (Uploads and stats don't count.)"""
        return any(j.kind in ("make", "draft", "clip", "plan") and j.status in ("queued", "running")
                   for j in list(self.jobs.values()))

    def autopilot_tick(self, now: float | None = None) -> Job | None:
        """Start the next autopilot video if one is due. Called every few seconds by its thread."""
        from . import autopilot, presets
        with self._ap_lock:  # the loop and the on switch may both get here at once: start one video, not two
            return self._autopilot_start(autopilot, presets, now)

    def _autopilot_start(self, autopilot, presets, now: float | None) -> Job | None:
        h = self.studio.history
        st = autopilot.load(h)
        if not autopilot.due(st, self.busy(), now):
            return None
        params = dict(presets.load(h).get(st["preset"], {}))
        has_ideas = bool(h.ideas("pending", 1))
        if has_ideas:
            params["source"] = "queue"
        params["upload"] = bool(st["upload"])
        params["autopilot"] = True
        autopilot.mark_started(h, now)
        label = "Autopilot: next idea from the queue" if has_ideas else "Autopilot: fresh topic from your niches"
        log.info("%s", label)
        return self.submit("make", params, label)

    def _autopilot_loop(self) -> None:
        while True:
            time.sleep(15)
            try:
                self.autopilot_tick()
            except Exception as e:  # never let the loop die
                log.warning("Autopilot: %s", e)

    def _update_loop(self) -> None:
        """Once a day, ask GitHub whether a newer release is out (see updates.py)."""
        from . import updates
        time.sleep(5)  # let the Studio open first
        while True:
            try:
                before = updates.available(self.studio.history)
                updates.check(self.studio.history)       # no-op unless the last check is a day old
                if updates.available(self.studio.history) != before:
                    self.changed()                       # the open page refreshes its info and shows the link
            except Exception as e:
                log.debug("Update check: %s", e)
            time.sleep(3600)

    def batch(self, topics: list, form: dict) -> list[int]:
        """One make job per topic, all with the same settings."""
        seen, out = set(), []
        for t in topics:
            t = " ".join(str(t or "").split())[:300]
            if t and t.lower() not in seen and len(out) < 50:
                seen.add(t.lower())
                out.append(self.submit("make", {**form, "topic": t, "source": None, "url": None}, t[:120]).id)
        return out

    def cancel(self, jid: int) -> bool:
        """Cancel a queued job, or stop the running one (its ffmpeg is stopped at once, the rest at the next
        stage)."""
        from . import ffmpeg
        from .utils import CANCEL
        job = self.jobs.get(jid)
        if job and job.status == "queued":
            job.status, job.finished = "cancelled", time.time()
            self.changed()
            return True
        if job and job.status == "running" and job.kind in LOCAL_KINDS:
            job.stop.set()
            job.message = "cancelling…"
            self.changed()
            return True
        if job and job.status == "running" and job is self.current:
            CANCEL.set()
            ffmpeg.kill_all()
            job.message = "cancelling…"
            self.changed()
            return True
        return False

    def _progress(self, job: Job):
        def cb(stage: str, pct: int, message: str) -> None:
            job.stage, job.pct = stage, max(job.pct, pct) if stage != "done" else 100
            job.message = message or job.message
            self.changed()
        return cb

    def overrides(self, p: dict) -> Settings:
        """Turn Create-form fields into Settings. Unknown values are ignored, never trusted."""
        from .overlays import CAPTION_STYLES
        from .render import GRADES, TRANSITIONS
        from .script import STYLES
        s = self.settings
        ov: dict = {
            "style": _choice(p.get("style"), STYLES),
            "language": (str(p.get("language") or "").strip().lower()[:8] or None),
            "tts_engine": _choice(p.get("tts"), ("edge", "openai", "elevenlabs", "kokoro", "coqui", "system")),
            "tts_voice": str(p.get("voice") or "").strip()[:200] or None,
            "tts_voice_b": str(p.get("voice_b") or "").strip()[:200] or None,
            "caption_style": _choice(p.get("caption_style"), CAPTION_STYLES),
            "caption_position": _choice(p.get("caption_position"), ("upper", "center", "lower")),
            "color_grade": _choice(p.get("grade"), GRADES),
            "transition": _choice(p.get("transition"), ["random", "none", *TRANSITIONS]),
            "llm_provider": str(p.get("provider") or "").strip().lower() or None,
            "llm_model": str(p.get("model") or "").strip()[:120] or None,
            "script_review": _choice(p.get("review"), ("off", "score", "rewrite")),
        }
        if p.get("duration"):
            try:
                ov["target_seconds"] = max(10, min(170, int(p["duration"])))
            except (TypeError, ValueError):
                pass
        if p.get("aspect") in ASPECTS:
            ov["resolution"] = aspect_resolution(p["aspect"])
        if isinstance(p.get("visuals"), list) and p["visuals"]:
            ov["visual_sources"] = [str(v).lower() for v in p["visuals"]][:6]
        if p.get("music") is False:
            ov["music_volume"] = 0.0
        if "background" in p:
            bg = str(p.get("background") or "").strip()[:1000]
            ov["background_video"] = bg if not bg or Path(bg).expanduser().exists() else None
        ov["background_layout"] = _choice(p.get("layout"), ("full", "split"))
        for key, field_name in (("sfx", "sound_effects"), ("emphasis", "caption_emphasis"), ("emoji", "caption_emoji"),
                                ("jump_cuts", "clip_jump_cuts"), ("zoom", "clip_zoom")):
            if isinstance(p.get(key), bool):
                ov[field_name] = p[key]
        s = s.with_overrides(**ov)
        if p.get("offline"):
            s = replace(s, offline=True)
        return s

    def _worker(self) -> None:
        from .pipeline import Studio
        from .utils import CANCEL, Cancelled, PermanentError
        while True:
            job = self.queue.get()
            if job.status == "cancelled":
                continue
            CANCEL.clear()
            self.current, job.status, job.started = job, "running", time.time()
            self.changed()
            p = job.params
            try:
                if job.kind == "upload":
                    status = self.studio.upload_record(int(p["id"]))
                    job.result = {"status": status, "id": int(p["id"])}
                    ok = status in ("uploaded", "scheduled", "queued")
                elif job.kind == "stats":
                    from .analytics import sync_stats
                    job.result = {"updated": sync_stats(self.settings, self.studio.history)}
                    ok = True
                else:
                    s = self.overrides(p)
                    studio = Studio(s, progress=self._progress(job))
                    job.eta_fn = studio.eta
                    ok = self._run(job, studio, s, p)
                job.status = "done" if ok else "failed"
            except Cancelled:
                job.status, job.message = "cancelled", "cancelled while running"
            except (PermanentError, ValueError, FileNotFoundError) as e:  # a setup or input problem: no traceback
                job.status, job.result = "failed", {"error": str(e)}
                log.warning("Failed: %s", e)
            except Exception as e:
                job.status, job.result = "failed", {"error": str(e)}
                log.exception("Studio job %d failed", job.id)
            finally:
                job.finished, job.eta_fn = time.time(), None
                if job.status == "done":
                    job.pct = 100
                self.current = None
                CANCEL.clear()
                self.changed()

    def _run(self, job: Job, studio, s: Settings, p: dict) -> bool:
        from .script import script_from_data
        if job.kind == "draft":
            script, pick, writer = studio.draft(p.get("topic") or None, source=p.get("source") or None,
                                                style=s.style if s.style != "auto" else None,
                                                url=p.get("url") or None)
            job.result = {"script": script.to_dict(), "source": pick.source, "llm": writer}
            job.stage, job.pct = "done", 100
            return True
        if job.kind == "plan":
            from .planner import plan_ideas
            niches = [p["niche"].strip()] if str(p.get("niche") or "").strip() else None
            job.stage, job.message = "script", f"writing ideas with {studio.llm.label if studio.llm else 'the AI'}"
            self.changed()
            ideas = plan_ideas(studio.llm, s, studio.history, int(p.get("count") or 10), niches)
            job.result = {"ideas": len(ideas)}
            job.stage, job.pct, job.message = "done", 100, f"{len(ideas)} idea(s) added to the queue"
            return bool(ideas)
        if job.kind == "clip":
            from .clipper import make_clips
            results = make_clips(studio, str(p.get("source") or ""), count=int(p.get("count") or 3),
                                 crop=p.get("crop") or "center", upload=bool(p.get("upload")) and s.upload,
                                 min_seconds=int(p.get("min_seconds") or 20), max_seconds=int(p.get("max_seconds") or 58),
                                 brief=str(p.get("brief") or "")[:500])
            job.result = {"clips": [_result(r) for r in results]}
            return any(r.ok for r in results)
        # make
        script = script_from_data(p["script"], s) if isinstance(p.get("script"), dict) else None
        langs = p.get("also_langs")
        if isinstance(langs, str):
            langs = [x.strip().lower() for x in langs.split(",") if x.strip()]
        # UPLOAD=false in .env is a hard stop, whatever a request asks for
        r = studio.make(p.get("topic") or None, source=p.get("source") or None,
                        upload=bool(p.get("upload")) and s.upload,
                        style=s.style if s.style != "auto" else None, script=script, url=p.get("url") or None,
                        languages=[str(x)[:8] for x in (langs or [])][:6])
        job.result = _result(r)
        return r.ok

    def _side_worker(self, lane: str) -> None:
        """Runs Local AI jobs one at a time per lane (downloads; speed tests and prefetches), next to the video
        worker, so a 5 GB download holds up neither a video nor a speed test."""
        from .utils import Cancelled
        while True:
            job = self.side[lane].get()
            if job.status == "cancelled":
                continue
            job.status, job.started = "running", time.time()
            self.lanes[threading.current_thread().name] = job
            self.changed()
            try:
                log.info("%s", job.label)
                job.status = "done" if self._local_job(job, job.params) else "failed"
                log.info("Done: %s", job.message)
            except Cancelled:
                job.status, job.message = "cancelled", "cancelled while running"
            except Exception as e:
                job.status, job.result = "failed", {"error": str(e)}
                log.warning("Studio job %d failed: %s", job.id, e)
            finally:
                self.lanes.pop(threading.current_thread().name, None)
                job.finished = time.time()
                self.changed()

    def _local_job(self, job: Job, p: dict) -> bool:
        """Local AI jobs: download an Ollama model, fetch offline voice/whisper files, or speed-test a model."""
        from . import localai
        progress = self._progress(job)
        if job.kind == "pull":
            if not localai.ollama_status()["running"] and not localai.start_ollama():
                raise RuntimeError("Ollama is not running. Install it from ollama.com, then start it.")
            localai.pull(str(p.get("model") or ""), progress, stop=job.stop)
            job.result = {"model": p.get("model")}
            job.message = f"{p.get('model')} downloaded"
        elif job.kind == "prefetch":
            from .tts import whisper_model
            name = str(p.get("whisper") or "") or whisper_model()
            job.result = {"message": localai.prefetch(str(p.get("what") or ""), progress, name)}
            job.message = job.result["message"]
        else:
            progress("test", 10, f"Loading {p.get('model')} and writing a short reply…")
            job.result = localai.benchmark(str(p.get("model") or ""))
            mins = job.result.get("script_minutes")
            job.message = f"{job.result['tokens_per_second']} tokens/s" + (f", a script in ~{mins} min" if mins else "")
        job.stage, job.pct = "done", 100
        return True

    def reload(self) -> None:
        """Pick up a changed .env: new keys, provider and defaults apply to the next job."""
        from .pipeline import Studio
        self.settings = Settings.from_env().with_overrides(**self._pinned)
        self.studio = Studio(self.settings)
        self._voices = {}
        self.changed()

    def local(self) -> dict:
        from . import localai
        st = localai.ollama_status()
        return {"ollama": st, "recommended": localai.recommended([m["name"] for m in st["models"]]),
                "offline": localai.offline_status(os.getenv("WHISPER_MODEL", "auto")),
                "provider": os.getenv("LLM_PROVIDER", ""), "model": os.getenv("LLM_MODEL", ""),
                "platform": sys.platform}

    # ------------------------------------------------------------------ data
    def videos(self, status: str = "", q: str = "") -> list[dict]:
        out = []
        for r in self.studio.history.recent(200):
            if status and r["status"] != status:
                continue
            if q and q.lower() not in f"{r['title']} {r['topic']} {r['subject']}".lower():
                continue
            folder = Path(r["folder"]) if r["folder"] else None
            video = Path(r["video_path"]) if r["video_path"] else None
            out.append({
                "id": r["id"], "title": r["title"], "status": r["status"], "created": r["created_at"],
                "youtube_id": r["youtube_id"], "publish_at": r["publish_at"], "duration": r["duration"],
                "style": r["style"], "language": r["language"], "score": r.get("score"),
                "views": r.get("views"), "likes": r.get("likes"), "parent_id": r.get("parent_id"),
                "video": video.name if video and video.exists() else None,
                "has_cover": bool(folder and (folder / "cover.jpg").exists()),
                "error": r["error"],
            })
        return out

    def video(self, vid: int) -> dict | None:
        rec = self.studio.history.get(vid)
        if not rec:
            return None
        folder = Path(rec["folder"]) if rec["folder"] else None
        data = dict(rec)
        data["tags"] = json.loads(rec["tags"] or "[]")
        for name in ("metadata", "script"):
            f = folder / f"{name}.json" if folder else None
            try:
                data[name] = json.loads(f.read_text(encoding="utf-8")) if f and f.exists() else None
            except (OSError, ValueError):
                data[name] = None
        video = Path(rec["video_path"]) if rec["video_path"] else None
        data["video"] = video.name if video and video.exists() else None
        data["has_cover"] = bool(folder and (folder / "cover.jpg").exists())
        data["has_srt"] = bool(folder and (folder / "captions.srt").exists())
        return data

    def file_for(self, vid: int, name: str) -> Path | None:
        if name not in FILES:
            return None
        rec = self.studio.history.get(vid)
        if not rec or not rec["folder"]:
            return None
        p = Path(rec["folder"]) / name
        return p if p.exists() else None

    def post_text(self, vid: int) -> str | None:
        """The post, ready to paste anywhere the app can't publish to: title, description, hashtags."""
        rec = self.studio.history.get(vid)
        if not rec:
            return None
        tags = [t for t in json.loads(rec["tags"] or "[]") if str(t).strip()]
        hashtags = " ".join("#" + re.sub(r"[^\w]+", "", str(t)) for t in tags if re.sub(r"[^\w]+", "", str(t)))
        parts = [f"TITLE\n{rec['title'] or ''}", f"DESCRIPTION\n{rec['description'] or ''}"]
        if hashtags:
            parts.append(f"HASHTAGS\n{hashtags}")
        return "\n\n".join(parts).strip() + "\n"

    def kit(self, vid: int):
        """Everything to post one video by hand, in one ZIP: the video, its cover, captions and post.txt.
        Videos are already compressed, so files are stored, not deflated (fast, same size). Returns an open
        temporary file (deleted on close) and a download name, or None."""
        import tempfile
        import zipfile
        rec = self.studio.history.get(vid)
        if not rec or not rec["folder"]:
            return None
        folder = Path(rec["folder"])
        video = Path(rec["video_path"]) if rec["video_path"] else None
        files = [(f, f.name) for f in ((video if video and video.exists() else None),
                                        folder / "cover.jpg", folder / "captions.srt") if f and f.exists()]
        if not files:
            return None
        tmp = tempfile.TemporaryFile()
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
            for f, name in files:
                z.write(f, name)
            z.writestr("post.txt", self.post_text(vid) or "", compress_type=zipfile.ZIP_DEFLATED)
        tmp.seek(0)
        return tmp, re.sub(r"[^\w.-]+", "-", folder.name)[:80] + ".zip"

    def voices(self, lang: str) -> list[dict]:
        lang = (lang or self.settings.language).lower()[:8]
        if lang not in self._voices:
            try:
                from .tts import list_edge_voices
                self._voices[lang] = [{"name": v["ShortName"], "gender": v["Gender"], "locale": v["Locale"]}
                                      for v in list_edge_voices(lang)]
            except Exception as e:
                log.warning("Could not list voices: %s", e)
                return []
        return self._voices[lang]

    def info(self) -> dict:
        s = self.settings
        from . import updates
        from .llm import LLMError, resolve_provider_name
        try:
            llm = f"{resolve_provider_name(s)}{(':' + s.llm_model) if s.llm_model else ''}"
            llm_ok = True
        except LLMError:
            llm, llm_ok = "not configured", False
        h = self.studio.history
        stats = h.stats()
        rows = h.recent(1000)
        views = sum(r.get("views") or 0 for r in rows)
        return {"version": __version__, "llm": llm, "llm_ok": llm_ok, "tts": s.tts_engine,
                "voice": s.tts_voice or "auto", "visuals": s.visual_sources, "upload": s.upload,
                "privacy": s.privacy, "quota_left": self.studio.quota_left(), "daily_limit": s.daily_upload_limit,
                "language": s.language, "caption_style": s.caption_style, "caption_position": s.caption_position,
                "duration": s.target_seconds, "style": s.style, "grade": s.color_grade, "transition": s.transition,
                "review": s.script_review, "aspect": next((k for k, v in ASPECTS.items() if v == s.resolution),
                                                          f"{s.width}x{s.height}"),
                "also_languages": s.also_languages, "learn_from_stats": s.learn_from_stats,
                "publish_to": s.publish_to,
                "counts": stats, "total": sum(stats.values()), "views": views,
                "seconds": round(sum(r.get("duration") or 0 for r in rows), 1),
                "formats": len({r.get("style") for r in rows if r.get("style")}),
                "ideas": len(h.ideas("pending")), "channel": s.channel_name,
                "update": updates.available(h) if s.check_updates else None,
                "credit_line": s.credit_line}

    def options(self) -> dict:
        from .llm import PRESETS, available_providers
        from .overlays import CAPTION_STYLES
        from .render import GRADES, TRANSITIONS
        from .script import LANGUAGES, STYLES
        ready = set(available_providers(self.settings))
        return {"styles": STYLES, "languages": LANGUAGES, "aspects": list(ASPECTS),
                "caption_styles": list(CAPTION_STYLES), "grades": list(GRADES),
                "transitions": ["random", "none", *TRANSITIONS],
                "providers": [{"name": n, "label": p.label, "ready": n in ready or p.local}
                              for n, p in PRESETS.items()],
                "tts": ["edge", "openai", "elevenlabs", "kokoro", "coqui", "system"],
                "visuals": ["pexels", "pixabay", "local", "pollinations", "openai-images"],
                "backgrounds": self.backgrounds(), "ollama_models": self._ollama_models(),
                "provider": os.getenv("LLM_PROVIDER", ""), "model": self.settings.llm_model or ""}

    def _ollama_models(self) -> list[str]:
        from .localai import ollama_status
        return [m["name"] for m in ollama_status()["models"]]

    def backgrounds(self) -> list[dict]:
        """Background videos to offer: BACKGROUND_VIDEO (a file, or every video in that folder) and
        media/backgrounds/."""
        from .media import VIDEO_EXT
        s = self.settings
        out: list[dict] = []
        if s.background_video:
            out.append({"path": s.background_video, "name": Path(s.background_video).name + (
                " (random)" if Path(s.background_video).expanduser().is_dir() else "")})
        for root in [Path(s.background_video).expanduser(), Path(s.media_dir) / "backgrounds"]:
            if not root.is_dir():
                continue
            for f in sorted(root.rglob("*")):
                if f.suffix.lower() in VIDEO_EXT and not f.name.startswith(".") and len(out) < 60:
                    item = {"path": str(f), "name": f.name}
                    if item not in out:
                        out.append(item)
        return out

    def channel(self) -> dict:
        from .analytics import calibration
        rows = [r for r in self.studio.history.recent(1000) if r.get("views") is not None]
        by_style: dict[str, list[int]] = {}
        for r in rows:
            by_style.setdefault(r["style"] or "other", []).append(r["views"])
        return {"videos": [{"id": r["id"], "title": r["title"], "views": r["views"], "likes": r["likes"],
                            "comments": r["comments"], "score": r.get("score"), "style": r["style"],
                            "youtube_id": r["youtube_id"]} for r in sorted(rows, key=lambda r: -r["views"])[:100]],
                "by_style": sorted(({"style": k, "videos": len(v), "avg_views": round(sum(v) / len(v))}
                                    for k, v in by_style.items()), key=lambda x: -x["avg_views"]),
                "synced": max((r.get("stats_at") or "" for r in rows), default=""),
                "calibration": calibration(self.studio.history)}


def _result(r) -> dict:
    return {"ok": r.ok, "title": r.title, "status": r.status, "youtube_id": r.youtube_id, "error": r.error,
            "id": r.record_id, "score": r.score, "language": r.language, "seconds": round(r.seconds, 1),
            "reason": getattr(r, "reason", ""), "posts": getattr(r, "posts", {}),
            "variants": [_result(v) for v in getattr(r, "variants", [])]}


def _handler(app: StudioServer, bound_host: str, password: str | None = None):
    loopback = bound_host in LOCAL_HOSTS
    password = os.getenv("STUDIO_PASSWORD", "") if password is None else password

    class H(BaseHTTPRequestHandler):
        server_version = f"PurffleStudio/{__version__}"

        def log_message(self, fmt, *args):  # keep the console for pipeline logs
            pass

        def _auth_ok(self) -> bool:
            """With STUDIO_PASSWORD set (for a Studio on a server), every request needs it (HTTP Basic)."""
            if not password:
                return True
            scheme, _, value = (self.headers.get("Authorization") or "").partition(" ")
            if scheme.lower() != "basic":
                return False
            try:
                _, _, given = base64.b64decode(value).decode("utf-8").partition(":")
            except (ValueError, UnicodeDecodeError):
                return False
            return hmac.compare_digest(given.encode(), password.encode())

        def _gate(self) -> bool:
            """True when the request may go on; otherwise the refusal has been sent."""
            if not self._host_ok():
                self._send(421, b"wrong host", "text/plain")
                return False
            if not self._auth_ok():
                self._send(401, b"password required", "text/plain",
                           {"WWW-Authenticate": 'Basic realm="PurffleShorts Studio", charset="UTF-8"'})
                return False
            return True

        def _events(self):
            """Server-sent events: the job list whenever anything changes (at most 4 times a second), and a
            comment every 15 s so proxies keep the connection open."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            seen = -1
            try:
                self.wfile.write(b"retry: 2000\n\n")
                while True:
                    version = app.wait_change(seen, 15.0)
                    if version != seen:
                        seen = version
                        data = json.dumps(app.jobs_public(), default=str)
                        self.wfile.write(f"event: jobs\ndata: {data}\n\n".encode())
                    else:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    time.sleep(0.25)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def _host_ok(self) -> bool:
            if not loopback:
                return True
            host = (self.headers.get("Host") or "").strip().lower()
            name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
            return name in LOCAL_HOSTS

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None, cache: str = "no-store"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200):
            self._send(code, json.dumps(data, default=str).encode(), "application/json")

        def do_GET(self):
            if not self._gate():
                return
            path, _, qs = self.path.partition("?")
            params = dict(x.partition("=")[::2] for x in qs.split("&") if x)
            from urllib.parse import unquote_plus
            params = {k: unquote_plus(v) for k, v in params.items()}
            if path == "/":
                html = (WEB / "index.html").read_text(encoding="utf-8")
                html = html.replace("__TOKEN__", app.token).replace("__VERSION__", __version__)
                return self._send(200, html.encode(), "text/html; charset=utf-8", {
                    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: https://i.ytimg.com; "
                                               "media-src 'self'; connect-src 'self'; frame-ancestors 'none'",
                    "X-Frame-Options": "DENY"})
            if path == "/favicon.ico":  # browsers ask for it whatever the page says
                return self._send(200, (WEB / "icon.svg").read_bytes(), "image/svg+xml")
            m = re.fullmatch(r"/static/([\w.-]+)", path)
            if m and m.group(1) in STATIC:
                return self._send(200, (WEB / m.group(1)).read_bytes(), STATIC[m.group(1)])
            m = re.fullmatch(r"/static/fonts/([\w-]+\.woff2)", path)
            if m and (WEB / "fonts" / m.group(1)).is_file():  # fonts never change within a version: cache them
                return self._send(200, (WEB / "fonts" / m.group(1)).read_bytes(), "font/woff2",
                                  cache="public, max-age=86400")
            if path == "/api/info":
                return self._json(app.info())
            if path == "/api/options":
                return self._json(app.options())
            if path == "/api/videos":
                return self._json(app.videos(params.get("status", ""), params.get("q", "")))
            m = re.fullmatch(r"/api/videos/(\d+)", path)
            if m:
                v = app.video(int(m.group(1)))
                return self._json(v) if v else self._json({"error": "not found"}, 404)
            if path == "/api/jobs":
                return self._json(app.jobs_public())
            if path == "/api/events":
                return self._events()
            m = re.fullmatch(r"/api/jobs/(\d+)", path)
            if m and int(m.group(1)) in app.jobs:
                return self._json(app.jobs[int(m.group(1))].public(full_log=True))
            if path == "/api/ideas":
                return self._json({"pending": app.studio.history.ideas("pending"),
                                   "used": app.studio.history.ideas("used", 30)})
            if path == "/api/doctor":
                from .doctor import checks
                return self._json(checks(app.settings))
            if path == "/api/channel":
                return self._json(app.channel())
            if path == "/api/voices":
                return self._json(app.voices(params.get("lang", "")))
            if path == "/api/settings":
                from . import envfile
                return self._json({**envfile.current(), "editable": self._settings_editable()})
            if path == "/api/local":
                return self._json(app.local())
            if path == "/api/presets":
                from . import presets
                return self._json(presets.load(app.studio.history))
            if path == "/api/autopilot":
                from . import autopilot
                return self._json(autopilot.public(autopilot.load(app.studio.history)))
            m = re.fullmatch(r"/files/(\d+)/(kit\.zip|post\.txt)", path)
            if m and m.group(2) == "post.txt":
                text = app.post_text(int(m.group(1)))
                return (self._send(200, text.encode("utf-8"), "text/plain; charset=utf-8") if text is not None
                        else self._send(404, b"not found", "text/plain"))
            if m:
                kit = app.kit(int(m.group(1)))
                if not kit:
                    return self._send(404, b"not found", "text/plain")
                tmp, name = kit
                with tmp:
                    tmp.seek(0, os.SEEK_END)
                    size = tmp.tell()
                    tmp.seek(0)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(size))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Content-Disposition", f'attachment; filename="{name}"')
                    self.end_headers()
                    try:
                        while chunk := tmp.read(1 << 16):
                            self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                return None
            m = re.fullmatch(r"/files/(\d+)/([\w.]+)", path)
            if m:
                f = app.file_for(int(m.group(1)), m.group(2))
                if not f:
                    return self._send(404, b"not found", "text/plain")
                return self._file(f, download="download" in params)
            self._send(404, b"not found", "text/plain")

        def _file(self, f: Path, download: bool = False):
            size = f.stat().st_size
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if f.suffix == ".srt":
                ctype = "text/plain; charset=utf-8"
            rng = self.headers.get("Range")
            start, end = 0, size - 1
            m = re.match(r"bytes=(\d*)-(\d*)", rng or "")
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("X-Content-Type-Options", "nosniff")
            if download:
                folder = re.sub(r"[^\w.-]+", "-", f.parent.name)[:80]
                self.send_header("Content-Disposition", f'attachment; filename="{folder}{f.suffix}"')
            self.end_headers()
            with open(f, "rb") as fh:
                fh.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = fh.read(min(1 << 16, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        def do_POST(self):
            if not self._gate():
                return
            if not hmac.compare_digest(self.headers.get("X-Studio-Token") or "", app.token):
                return self._json({"error": "bad token"}, 403)
            length = min(int(self.headers.get("Content-Length") or 0), 512 * 1024)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            if not isinstance(body, dict):
                return self._json({"error": "expected an object"}, 400)
            path = self.path
            h = app.studio.history
            if path in ("/api/make", "/api/draft"):
                kind = "make" if path == "/api/make" else "draft"
                label = (body.get("script") or {}).get("title") if isinstance(body.get("script"), dict) else None
                label = (label or body.get("topic") or body.get("url")
                         or ("Demo video" if body.get("offline") else
                             "Next idea from the queue" if body.get("source") == "queue" else "AI-picked topic"))
                return self._json({"job": app.submit(kind, body, str(label)[:120]).id})
            if path == "/api/clip":
                if not str(body.get("source") or "").strip():
                    return self._json({"error": "give a video file path or URL"}, 400)
                src = str(body["source"]).strip()
                name = src if re.match(r"^https?://", src) else (Path(src).name or src)
                return self._json({"job": app.submit("clip", body, f"Clip: {name[:100]}").id})
            if path == "/api/plan":
                label = f"Plan {body.get('count') or 10} ideas" + (f" · {body['niche']}" if body.get("niche") else "")
                return self._json({"job": app.submit("plan", body, label).id})
            if path == "/api/stats":
                return self._json({"job": app.submit("stats", {}, "Refresh channel stats").id})
            if path == "/api/ideas":
                subject = str(body.get("subject") or "").strip()
                if not subject:
                    return self._json({"error": "empty idea"}, 400)
                from .script import STYLES
                return self._json({"id": h.add_idea(subject[:300], _choice(body.get("style"), STYLES, ""),
                                                    str(body.get("notes") or "")[:500])})
            m = re.fullmatch(r"/api/ideas/(\d+)/delete", path)
            if m:
                h.delete_idea(int(m.group(1)))
                return self._json({"ok": True})
            m = re.fullmatch(r"/api/upload/(\d+)", path)
            if m:
                rec = h.get(int(m.group(1)))
                label = f"Upload: {rec['title']}" if rec else f"Upload #{m.group(1)}"
                return self._json({"job": app.submit("upload", {"id": int(m.group(1))}, label).id})
            m = re.fullmatch(r"/api/videos/(\d+)/delete", path)
            if m:
                return self._json({"ok": app.studio.delete(int(m.group(1)))})
            m = re.fullmatch(r"/api/jobs/(\d+)/cancel", path)
            if m:
                return self._json({"ok": app.cancel(int(m.group(1)))})
            if path == "/api/settings":
                return self._save_settings(body.get("values"))
            if path == "/api/batch":
                topics = body.get("topics")
                if isinstance(topics, str):
                    topics = topics.splitlines()
                if not isinstance(topics, list) or not any(str(t).strip() for t in topics):
                    return self._json({"error": "give one topic per line"}, 400)
                form = {k: v for k, v in body.items() if k not in ("topics", "script")}
                return self._json({"jobs": app.batch(topics, form)})
            if path in ("/api/presets", "/api/presets/delete"):
                from . import presets
                try:
                    if path.endswith("/delete"):
                        return self._json(presets.delete(h, body.get("name")))
                    return self._json(presets.save(h, body.get("name"), body.get("form") or {}))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
            if path == "/api/autopilot":
                from . import autopilot
                try:
                    st = autopilot.update(h, body)
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                app.autopilot_tick()   # turned on: the first video starts now, not in 15 seconds
                app.changed()
                return self._json(autopilot.public(autopilot.load(h)) if st else {})
            if path.startswith("/api/local/"):
                return self._local_post(path.rsplit("/", 1)[1], body)
            self._json({"error": "not found"}, 404)

        def _settings_editable(self) -> bool:
            # keys can be written from this machine, or over the network only behind STUDIO_PASSWORD
            return bound_host in LOCAL_HOSTS or bool(password or os.getenv("STUDIO_PASSWORD"))

        def _save_settings(self, values):
            from . import envfile
            if not self._settings_editable():
                return self._json({"error": "Settings can only be changed on this computer, or with "
                                            "STUDIO_PASSWORD set"}, 403)
            if not isinstance(values, dict):
                return self._json({"error": "expected values"}, 400)
            try:
                updates = envfile.clean(values)
            except ValueError as e:
                return self._json({"error": str(e)}, 400)
            if updates:
                envfile.write(updates)
                envfile.apply(updates)
                app.reload()
            return self._json({"ok": True, "changed": sorted(updates), **envfile.current()})

        def _local_post(self, action: str, body: dict):
            from . import envfile, localai
            model = str(body.get("model") or "").strip()
            if action in ("pull", "delete", "bench", "default") and not localai.valid_model_name(model):
                return self._json({"error": "give a model name like qwen3.5:4b"}, 400)
            if action == "pull":
                return self._json({"job": app.submit("pull", {"model": model}, f"Download {model}").id})
            if action == "bench":
                return self._json({"job": app.submit("bench", {"model": model}, f"Speed test: {model}").id})
            if action == "prefetch":
                what = _choice(body.get("what"), ("kokoro", "whisper"))
                if not what:
                    return self._json({"error": "unknown download"}, 400)
                label = "Download Kokoro voice" if what == "kokoro" else "Download Whisper model"
                return self._json({"job": app.submit("prefetch", {"what": what,
                                                                  "whisper": body.get("whisper") or ""}, label).id})
            if action == "delete":
                return self._json({"ok": localai.delete(model)})
            if action == "start":
                return self._json({"ok": localai.start_ollama()})
            if action == "default":
                if not self._settings_editable():
                    return self._json({"error": "not allowed from the network"}, 403)
                updates = {"LLM_PROVIDER": "ollama", "LLM_MODEL": model}
                envfile.write(updates)
                envfile.apply(updates)
                app.reload()
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)

    return H


class StudioHTTPServer(ThreadingHTTPServer):
    """Leaves out the traceback when the browser closes a connection early (a reload, or leaving a page
    while it loads): that is normal, not an error."""

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    app = StudioServer(settings)
    httpd = StudioHTTPServer((host, port), _handler(app, host))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}/"
    log.info("PurffleShorts Studio running at %s  (Ctrl+C to stop)", url)
    if host not in LOCAL_HOSTS and not os.getenv("STUDIO_PASSWORD"):
        log.warning("Studio is reachable from your network on %s — anyone who can load the page can use it. "
                    "Set STUDIO_PASSWORD to require a password.", host)
    elif os.getenv("STUDIO_PASSWORD"):
        log.info("Studio password is on (any user name, the password from STUDIO_PASSWORD)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
