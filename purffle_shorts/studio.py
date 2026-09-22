"""PurffleShorts Studio — a small local web dashboard (standard library only).

    python -m purffle_shorts studio        -> http://127.0.0.1:8765

Create videos from a form, watch progress live, preview renders and upload them with one click.
It binds to localhost and every write request needs a per-session token, so other websites
can't drive it from your browser.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import queue
import re
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .config import Settings

log = logging.getLogger("purffle")


@dataclass
class Job:
    id: int
    params: dict
    status: str = "queued"          # queued | running | done | failed
    log: list[str] = field(default_factory=list)
    result: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)


class _JobLog(logging.Handler):
    """Copies log lines produced by the worker thread into the running job."""

    def __init__(self, studio: StudioServer):
        super().__init__(logging.INFO)
        self.studio = studio
        self.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        job = self.studio.current
        if job is not None and record.threadName == "studio-worker":
            job.log.append(self.format(record))
            del job.log[:-200]


class StudioServer:
    def __init__(self, settings: Settings):
        from .pipeline import Studio
        self.settings = settings
        self.studio = Studio(settings)
        self.token = secrets.token_urlsafe(24)
        self.jobs: dict[int, Job] = {}
        self.queue: queue.Queue[Job] = queue.Queue()
        self.current: Job | None = None
        self._next = 1
        logging.getLogger().addHandler(_JobLog(self))
        threading.Thread(target=self._worker, name="studio-worker", daemon=True).start()

    def submit(self, params: dict) -> Job:
        job = Job(self._next, params)
        self._next += 1
        self.jobs[job.id] = job
        self.queue.put(job)
        return job

    def _worker(self) -> None:
        from .pipeline import Studio
        while True:
            job = self.queue.get()
            self.current, job.status = job, "running"
            p = job.params
            try:
                if p.get("action") == "upload":
                    status = self.studio.upload_record(int(p["id"]))
                    job.status = "done" if status in ("uploaded", "scheduled", "queued") else "failed"
                    job.result = {"status": status}
                    continue
                overrides = {k: v for k, v in {
                    "style": p.get("style") or None, "language": p.get("language") or None,
                    "tts_voice": p.get("voice") or None, "tts_engine": p.get("tts") or None,
                    "caption_style": p.get("caption_style") or None,
                    "target_seconds": int(p["duration"]) if p.get("duration") else None,
                    "llm_provider": p.get("provider") or None, "llm_model": p.get("model") or None,
                }.items() if v is not None}
                s = self.settings.with_overrides(**overrides)
                if p.get("offline"):
                    s = replace(s, offline=True)
                studio = self.studio if s == self.settings else Studio(s)
                r = studio.make(p.get("topic") or None, source=p.get("source") or None, upload=bool(p.get("upload")))
                job.status = "done" if r.ok else "failed"
                job.result = {"ok": r.ok, "title": r.title, "status": r.status, "youtube_id": r.youtube_id,
                              "error": r.error, "id": r.record_id}
            except Exception as e:
                job.status, job.result = "failed", {"error": str(e)}
                log.exception("Studio job %d failed", job.id)
            finally:
                self.current = None

    def videos(self) -> list[dict]:
        out = []
        for r in self.studio.history.recent(60):
            folder = Path(r["folder"]) if r["folder"] else None
            out.append({
                "id": r["id"], "title": r["title"], "status": r["status"], "created": r["created_at"],
                "youtube_id": r["youtube_id"], "publish_at": r["publish_at"], "duration": r["duration"],
                "has_video": bool(r["video_path"] and Path(r["video_path"]).exists()),
                "has_cover": bool(folder and (folder / "cover.jpg").exists()),
                "error": r["error"],
            })
        return out

    def file_for(self, vid: int, name: str) -> Path | None:
        if name not in ("short.mp4", "cover.jpg", "captions.srt", "metadata.json"):
            return None
        rec = self.studio.history.get(vid)
        if not rec or not rec["folder"]:
            return None
        p = Path(rec["folder"]) / name
        return p if p.exists() else None

    def info(self) -> dict:
        s = self.settings
        from .llm import LLMError, resolve_provider_name
        try:
            llm = f"{resolve_provider_name(s)}{(':' + s.llm_model) if s.llm_model else ''}"
        except LLMError:
            llm = "not configured (demo mode only)"
        return {"version": __version__, "llm": llm, "tts": s.tts_engine, "voice": s.tts_voice or "auto",
                "visuals": ", ".join(s.visual_sources), "upload": s.upload, "privacy": s.privacy,
                "quota_left": self.studio.quota_left(), "language": s.language,
                "caption_style": s.caption_style, "duration": s.target_seconds}


def _handler(app: StudioServer):
    class H(BaseHTTPRequestHandler):
        server_version = f"PurffleStudio/{__version__}"

        def log_message(self, fmt, *args):  # keep the console for pipeline logs
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200):
            self._send(code, json.dumps(data).encode(), "application/json")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/":
                html = PAGE.replace("__TOKEN__", app.token).replace("__VERSION__", __version__)
                return self._send(200, html.encode(), "text/html; charset=utf-8",
                                  {"Content-Security-Policy": "default-src 'self'; style-src 'unsafe-inline'; "
                                   "script-src 'unsafe-inline'; img-src 'self' data:; media-src 'self'"})
            if path == "/api/info":
                return self._json(app.info())
            if path == "/api/videos":
                return self._json(app.videos())
            if path == "/api/jobs":
                jobs = sorted(app.jobs.values(), key=lambda j: j.id, reverse=True)[:20]
                return self._json([{"id": j.id, "status": j.status, "params": j.params, "result": j.result,
                                    "log": j.log[-40:]} for j in jobs])
            m = re.fullmatch(r"/files/(\d+)/([\w.]+)", path)
            if m:
                f = app.file_for(int(m.group(1)), m.group(2))
                if not f:
                    return self._send(404, b"not found", "text/plain")
                return self._file(f)
            self._send(404, b"not found", "text/plain")

        def _file(self, f: Path):
            size = f.stat().st_size
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
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
            if self.headers.get("X-Studio-Token") != app.token:
                return self._json({"error": "bad token"}, 403)
            length = min(int(self.headers.get("Content-Length") or 0), 64 * 1024)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._json({"error": "bad json"}, 400)
            if self.path == "/api/make":
                job = app.submit({k: body.get(k) for k in (
                    "topic", "source", "style", "language", "voice", "tts", "caption_style", "duration",
                    "provider", "model", "upload", "offline")})
                return self._json({"job": job.id})
            m = re.fullmatch(r"/api/upload/(\d+)", self.path)
            if m:
                job = app.submit({"action": "upload", "id": int(m.group(1))})
                return self._json({"job": job.id})
            self._json({"error": "not found"}, 404)

    return H


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    app = StudioServer(settings)
    httpd = ThreadingHTTPServer((host, port), _handler(app))
    url = f"http://{host}:{port}/"
    log.info("PurffleShorts Studio running at %s  (Ctrl+C to stop)", url)
    if host not in ("127.0.0.1", "localhost"):
        log.warning("Studio is reachable from your network on %s — anyone who can load the page can use it.", host)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PurffleShorts Studio</title>
<style>
:root{--bg:#0e0f13;--panel:#171922;--line:#2a2d3a;--text:#e9eaf0;--muted:#9a9db0;--accent:#ffe11a;--ok:#3ddc84;--bad:#ff5c7a;--blue:#7aa2ff}
@media (prefers-color-scheme: light){:root{--bg:#f6f7fb;--panel:#fff;--line:#e3e5ee;--text:#16181f;--muted:#5d6173;--accent:#b88a00;--ok:#138a4b;--bad:#c62846;--blue:#2d5bd7}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:16px 20px;border-bottom:1px solid var(--line);flex-wrap:wrap}
h1{font-size:18px;margin:0}h1 b{color:var(--accent)}h2{font-size:15px;margin:0 0 12px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.chips{display:flex;gap:8px;flex-wrap:wrap}.chip{background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:3px 10px;font-size:13px;color:var(--muted)}
main{display:grid;grid-template-columns:minmax(280px,360px) 1fr;gap:20px;padding:20px;max-width:1400px;margin:0 auto}
@media (max-width:860px){main{grid-template-columns:1fr;padding:16px}}
section{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}
label{display:block;font-size:13px;color:var(--muted);margin:10px 0 4px}
input,select{width:100%;padding:9px 10px;border-radius:9px;border:1px solid var(--line);background:var(--bg);color:var(--text);font:inherit}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.check{display:flex;gap:8px;align-items:center;margin-top:12px;color:var(--text)}.check input{width:auto}
button{cursor:pointer;border:0;border-radius:10px;padding:10px 14px;font:600 14px system-ui;background:var(--accent);color:#111}
button.ghost{background:transparent;border:1px solid var(--line);color:var(--text);padding:6px 10px;font-weight:500}
#go{width:100%;margin-top:16px}
.job{border-top:1px solid var(--line);padding:10px 0}.job:first-child{border-top:0}
.st{font-size:12px;font-weight:700;text-transform:uppercase}.st.running{color:var(--blue)}.st.done{color:var(--ok)}.st.failed{color:var(--bad)}.st.queued{color:var(--muted)}
pre{white-space:pre-wrap;word-break:break-word;font:12px/1.45 ui-monospace,Menlo,monospace;color:var(--muted);max-height:180px;overflow:auto;margin:6px 0 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px}
.card{border:1px solid var(--line);border-radius:12px;overflow:hidden;background:var(--bg)}
.card video,.card img,.ph{width:100%;aspect-ratio:9/16;display:block;background:#000;object-fit:cover}
.ph{display:flex;align-items:center;justify-content:center;color:var(--muted);font-size:13px}
.meta{padding:10px}.meta b{display:block;font-size:14px;line-height:1.35;margin-bottom:6px}
.meta a{color:var(--blue)}.small{font-size:12px;color:var(--muted)}.actions{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
</style></head><body>
<header><h1><b>▶</b> PurffleShorts Studio <span class="small">v__VERSION__</span></h1><div class="chips" id="chips"></div></header>
<main>
<div>
<section>
<h2>Create a Short</h2>
<label for="topic">Topic (leave empty to let the AI pick)</label><input id="topic" placeholder="e.g. Why octopuses have three hearts">
<div class="row"><div><label for="source">Idea source</label><select id="source"><option value="">auto</option><option>niche</option><option>trending</option><option>wikipedia</option><option>reddit</option><option>file</option></select></div>
<div><label for="style">Format</label><select id="style"><option value="">auto</option><option>facts</option><option>story</option><option>listicle</option><option>myth</option><option>quiz</option><option>explainer</option><option>motivational</option><option>news</option></select></div></div>
<div class="row"><div><label for="language">Language</label><input id="language" placeholder="en"></div>
<div><label for="duration">Seconds</label><input id="duration" type="number" min="10" max="170" placeholder="40"></div></div>
<div class="row"><div><label for="caption_style">Captions</label><select id="caption_style"><option value="">default</option><option>bold</option><option>boxed</option><option>neon</option><option>clean</option><option>karaoke</option><option>minimal</option></select></div>
<div><label for="tts">Voice engine</label><select id="tts"><option value="">default</option><option>edge</option><option>openai</option><option>elevenlabs</option><option>kokoro</option><option>coqui</option><option>system</option></select></div></div>
<label for="voice">Voice (optional)</label><input id="voice" placeholder="en-US-AndrewMultilingualNeural">
<div class="row"><div><label for="provider">LLM provider</label><input id="provider" placeholder="auto"></div>
<div><label for="model">Model</label><input id="model" placeholder="default"></div></div>
<label class="check"><input type="checkbox" id="upload"> Upload to YouTube when done</label>
<label class="check"><input type="checkbox" id="offline"> Demo mode (no API keys)</label>
<button id="go">Create video</button>
</section>
<section style="margin-top:20px"><h2>Jobs</h2><div id="jobs" class="small">No jobs yet.</div></section>
</div>
<section><h2>Library</h2><div class="grid" id="videos"></div></section>
</main>
<script>
const TOKEN="__TOKEN__";
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
async function post(url,body){const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json","X-Studio-Token":TOKEN},body:JSON.stringify(body||{})});return r.json()}
async function info(){const i=await (await fetch("/api/info")).json();
 $("chips").innerHTML=[["LLM",i.llm],["Voice",i.tts+" / "+i.voice],["Visuals",i.visuals],["Captions",i.caption_style],["Upload",i.upload?i.privacy:"off"],["Uploads left today",i.quota_left]].map(([k,v])=>`<span class="chip">${esc(k)}: ${esc(v)}</span>`).join("");
 $("upload").checked=!!i.upload}
async function jobs(){const js=await (await fetch("/api/jobs")).json(); if(!js.length)return;
 $("jobs").innerHTML=js.map(j=>`<div class="job"><span class="st ${j.status}">${j.status}</span> #${j.id} ${esc(j.params.action==="upload"?"upload video "+j.params.id:(j.params.topic||"AI-picked topic"))}
 ${j.result&&j.result.title?`<div>${esc(j.result.title)} — ${esc(j.result.status)}</div>`:""}${j.result&&j.result.error?`<div style="color:var(--bad)">${esc(j.result.error)}</div>`:""}
 ${j.status==="running"||j.status==="failed"?`<pre>${esc(j.log.join("\n"))}</pre>`:""}</div>`).join("")}
async function videos(){const vs=await (await fetch("/api/videos")).json();
 $("videos").innerHTML=vs.length?vs.map(v=>`<div class="card">${v.has_video?`<video src="/files/${v.id}/short.mp4" controls preload="none" poster="${v.has_cover?`/files/${v.id}/cover.jpg`:""}"></video>`:(v.has_cover?`<img src="/files/${v.id}/cover.jpg" alt="">`:`<div class="ph">no preview</div>`)}
 <div class="meta"><b>${esc(v.title)}</b><span class="small">#${v.id} · ${esc(v.status)} · ${v.duration?v.duration.toFixed(1)+"s":""}</span>
 ${v.youtube_id?`<div><a href="https://youtube.com/shorts/${esc(v.youtube_id)}" target="_blank" rel="noopener">Open on YouTube</a></div>`:""}
 ${v.publish_at?`<div class="small">goes public ${esc(v.publish_at)}</div>`:""}
 <div class="actions">${v.has_video&&!v.youtube_id?`<button class="ghost" data-up="${v.id}">Upload</button>`:""}</div></div></div>`).join(""):`<div class="small">Nothing yet — create your first Short.</div>`;
 document.querySelectorAll("[data-up]").forEach(b=>b.onclick=async()=>{b.disabled=true;await post("/api/upload/"+b.dataset.up);jobs()})}
$("go").onclick=async()=>{const body={};["topic","source","style","language","duration","caption_style","tts","voice","provider","model"].forEach(k=>body[k]=$(k).value.trim());
 body.upload=$("upload").checked;body.offline=$("offline").checked;await post("/api/make",body);jobs()};
info();jobs();videos();setInterval(jobs,2000);setInterval(videos,8000);
</script></body></html>
"""
