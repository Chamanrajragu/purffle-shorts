"""PurffleShorts as an MCP server, so Claude Desktop, Claude Code, Cursor or any MCP client can make videos:

    "Make a 30-second Short about why cats purr, in Spanish, and don't upload it."

Add it to your client's MCP config (it speaks MCP over stdio, standard library only):

    {"mcpServers": {"purffle-shorts": {"command": "purffle-shorts", "args": ["mcp"],
                                       "env": {"PURFFLE_HOME": "/path/to/your/purffle/folder"}}}}

PURFFLE_HOME is the folder that holds your .env, credentials and output (defaults to the current folder).
Uploading only happens when the client asks for it explicitly (upload: true).
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from dataclasses import replace
from typing import Any

from . import __version__
from .config import Settings

log = logging.getLogger("purffle")

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

_STYLE = {"type": "string", "enum": ["auto", "facts", "story", "listicle", "myth", "quiz", "motivational", "news",
                                     "explainer", "dialogue", "chat", "reddit"],
          "description": "Video format. dialogue = two voices talking; chat = animated text-message story; "
                         "reddit = first-person story that opens on a post card."}
TOOLS: list[dict] = [
    {"name": "make_short",
     "description": "Write, voice and render a complete short video (script, voice, footage, captions, music) and "
                    "return where it was saved. Takes 1-3 minutes. Does NOT upload unless upload is true.",
     "inputSchema": {"type": "object", "properties": {
         "topic": {"type": "string", "description": "What the video is about. Empty = the app picks a topic."},
         "url": {"type": "string", "description": "Make the video from this web page (article, blog post)."},
         "style": _STYLE,
         "language": {"type": "string", "description": "Language code, e.g. en, es, hi, ta, fr, ja."},
         "duration_seconds": {"type": "integer", "minimum": 10, "maximum": 170},
         "aspect": {"type": "string", "enum": ["9:16", "16:9", "1:1", "4:5"]},
         "script": {"type": "object", "description": "A script from draft_script (optionally edited) to render "
                                                     "exactly, instead of writing a new one."},
         "also_languages": {"type": "array", "items": {"type": "string"},
                            "description": "Also make translated copies, e.g. [\"es\", \"hi\"]."},
         "upload": {"type": "boolean", "description": "Upload to YouTube when done. Default false."},
         "demo": {"type": "boolean", "description": "No-key demo: sample script and generated backgrounds."}}}},
    {"name": "draft_script",
     "description": "Write (and self-review) a video script without rendering it. Returns the script JSON, which "
                    "can be edited and passed to make_short.",
     "inputSchema": {"type": "object", "properties": {
         "topic": {"type": "string"}, "url": {"type": "string"}, "style": _STYLE,
         "language": {"type": "string"}, "duration_seconds": {"type": "integer", "minimum": 10, "maximum": 170}}}},
    {"name": "clip_video",
     "description": "Cut a long video (local file path, or URL if yt-dlp is installed) into short vertical clips "
                    "of its best moments, with captions. Only for videos the user owns or may reuse.",
     "inputSchema": {"type": "object", "required": ["source"], "properties": {
         "source": {"type": "string"}, "count": {"type": "integer", "minimum": 1, "maximum": 10},
         "crop": {"type": "string", "enum": ["center", "blur"]}, "upload": {"type": "boolean"}}}},
    {"name": "plan_ideas",
     "description": "Brainstorm specific video ideas and add them to the idea queue that the autopilot uses first.",
     "inputSchema": {"type": "object", "properties": {
         "count": {"type": "integer", "minimum": 1, "maximum": 50}, "niche": {"type": "string"}}}},
    {"name": "list_videos",
     "description": "List recent videos with id, status, title, YouTube link and retention score.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}}},
    {"name": "upload_video",
     "description": "Upload (or schedule, if publish times are set) a rendered video to YouTube by its id.",
     "inputSchema": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}}},
]


class Server:
    def __init__(self, settings: Settings):
        self.settings = settings

    # ---------------------------------------------------------------- tools
    def _settings(self, a: dict) -> Settings:
        from .config import aspect_resolution
        s = self.settings.with_overrides(
            style=a.get("style") or None, language=(a.get("language") or "").lower() or None,
            target_seconds=max(10, min(170, int(a["duration_seconds"]))) if a.get("duration_seconds") else None)
        if a.get("aspect") and aspect_resolution(a["aspect"]):
            s = replace(s, resolution=aspect_resolution(a["aspect"]))
        if a.get("demo"):
            s = replace(s, offline=True, upload=False)
        return s

    def make_short(self, a: dict) -> str:
        from .pipeline import Studio
        from .script import STYLES, script_from_data
        s = self._settings(a)
        studio = Studio(s)
        script = script_from_data(a["script"], s) if isinstance(a.get("script"), dict) else None
        r = studio.make(a.get("topic") or None, url=a.get("url") or None, script=script,
                        style=s.style if s.style in STYLES else None,
                        upload=bool(a.get("upload")) and not s.offline, languages=a.get("also_languages") or [])
        if not r.ok:
            raise RuntimeError(r.error or "the video failed")
        lines = [_describe(r)] + [_describe(v) for v in r.variants]
        return "\n\n".join(lines)

    def draft_script(self, a: dict) -> str:
        from .pipeline import Studio
        script, pick, writer = Studio(self._settings(a)).draft(a.get("topic") or None, url=a.get("url") or None)
        return json.dumps(script.to_dict(), indent=2, ensure_ascii=False)

    def clip_video(self, a: dict) -> str:
        from .clipper import make_clips
        from .pipeline import Studio
        results = make_clips(Studio(self.settings), a["source"], count=int(a.get("count") or 3),
                             crop=a.get("crop") or "center", upload=bool(a.get("upload")))
        return "\n\n".join(_describe(r) for r in results) or "No clips were made."

    def plan_ideas(self, a: dict) -> str:
        from .pipeline import Studio
        from .planner import plan_ideas
        studio = Studio(self.settings)
        niches = [a["niche"]] if a.get("niche") else None
        ideas = plan_ideas(studio.llm, self.settings, studio.history, int(a.get("count") or 10), niches)
        return "\n".join(f"#{i['id']} [{i['style'] or 'auto'}] {i['subject']} — {i['notes']}" for i in ideas) \
            or "No new ideas."

    def list_videos(self, a: dict) -> str:
        from .history import History
        rows = History(self.settings.data_path / "history.db").recent(int(a.get("limit") or 20))
        if not rows:
            return "No videos yet."
        out = []
        for r in rows:
            link = f" https://youtube.com/shorts/{r['youtube_id']}" if r["youtube_id"] else ""
            score = f" score {r['score']}" if r.get("score") is not None else ""
            out.append(f"#{r['id']} {r['status']}{score}: {r['title']}{link}")
        return "\n".join(out)

    def upload_video(self, a: dict) -> str:
        from .pipeline import Studio
        status = Studio(self.settings).upload_record(int(a["id"]))
        return f"Video #{a['id']}: {status}"

    # ---------------------------------------------------------------- protocol
    def handle(self, msg: dict) -> dict | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:  # notification (e.g. notifications/initialized): no reply
            return None
        try:
            if method == "initialize":
                asked = (msg.get("params") or {}).get("protocolVersion")
                return _ok(mid, {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                                 "capabilities": {"tools": {"listChanged": False}},
                                 "serverInfo": {"name": "purffle-shorts", "version": __version__},
                                 "instructions": "Tools to write, render and publish short videos. make_short "
                                                 "and clip_video take minutes; upload only when the user asks."})
            if method == "ping":
                return _ok(mid, {})
            if method == "tools/list":
                return _ok(mid, {"tools": TOOLS})
            if method == "tools/call":
                params = msg.get("params") or {}
                name, args = params.get("name"), params.get("arguments") or {}
                if name not in {t["name"] for t in TOOLS}:
                    return _err(mid, -32602, f"Unknown tool: {name}")
                try:
                    text = getattr(self, name)(args)
                    return _ok(mid, {"content": [{"type": "text", "text": text}], "isError": False})
                except Exception as e:  # tool errors are results the model can read, not protocol errors
                    log.error("MCP tool %s failed: %s", name, e)
                    log.debug(traceback.format_exc())
                    return _ok(mid, {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})
            return _err(mid, -32601, f"Method not found: {method}")
        except Exception as e:
            return _err(mid, -32603, str(e))

    def serve(self, stdin=None, stdout=None) -> None:
        stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
        log.info("PurffleShorts MCP server %s ready on stdio", __version__)
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                reply = _err(None, -32700, "Parse error")
            else:
                reply = self.handle(msg) if isinstance(msg, dict) else _err(None, -32600, "Invalid request")
            if reply is not None:
                stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                stdout.flush()


def _ok(mid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _describe(r) -> str:
    if not r.ok:
        return f"✘ {r.language or ''} failed: {r.error}".strip()
    parts = [f"✔ {r.title}", f"  id: {r.record_id}", f"  status: {r.status}"]
    if r.video:
        parts.append(f"  file: {r.video}")
    if r.score is not None:
        parts.append(f"  retention score: {r.score}/100")
    if r.youtube_id:
        parts.append(f"  https://youtube.com/shorts/{r.youtube_id}")
    return "\n".join(parts)
