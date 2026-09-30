"""Command line: `purffle-shorts <command>` or `python -m purffle_shorts <command>`."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from . import __version__
from .config import ASPECTS, ConfigError, Settings, aspect_resolution, load_env, parse_resolution

log = logging.getLogger("purffle")


def setup_logging(settings: Settings, verbose: bool = False, stream=None) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    console = logging.StreamHandler(stream or sys.stdout)
    console.setFormatter(fmt)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logs = settings.data_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    file = logging.handlers.RotatingFileHandler(logs / "purffle.log", maxBytes=5_000_000, backupCount=3,
                                                encoding="utf-8")
    file.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(threadName)s %(message)s"))
    root.addHandler(console)
    root.addHandler(file)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for noisy in ("urllib3", "googleapiclient", "google", "httpx", "anthropic", "PIL", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("content & models")
    g.add_argument("--topic", help="make a video about exactly this")
    g.add_argument("--source", choices=["niche", "trending", "wikipedia", "reddit", "rss", "file", "queue"],
                   help="topic source")
    g.add_argument("--niche", action="append", help="niche to pick topics from (repeatable)")
    g.add_argument("--style", help="facts|story|listicle|myth|quiz|motivational|news|explainer|dialogue|chat|reddit|auto")
    g.add_argument("--lang", dest="language", help="language code, e.g. en, es, hi, ta, fr, ja")
    g.add_argument("--duration", dest="target_seconds", type=int, help="target length in seconds (15-170)")
    g.add_argument("--provider", dest="llm_provider", help="LLM provider (see `providers`)")
    g.add_argument("--model", dest="llm_model", help="LLM model name")
    g.add_argument("--tts", dest="tts_engine", help="edge|openai|elevenlabs|kokoro|coqui|system|silent")
    g.add_argument("--voice", dest="tts_voice", help="voice name/id (comma list = rotate)")
    g.add_argument("--voice-b", dest="tts_voice_b", help="second speaker's voice (dialogue and chat formats)")
    g.add_argument("--no-review", action="store_true", help="skip the Script Doctor's second pass")
    g.add_argument("--also-lang", help="also make translated copies, e.g. es,hi (same footage)")
    g.add_argument("--visuals", help="comma list: pexels,pixabay,local,openai-images,pollinations")
    r = p.add_argument_group("look & output")
    r.add_argument("--caption-style", help="bold|boxed|neon|clean|karaoke|minimal")
    r.add_argument("--caption-position", help="upper|center|lower")
    r.add_argument("--grade", dest="color_grade", help="none|vivid|cinematic|warm|cool|bw")
    r.add_argument("--transition", help="random|none|fade|slideup|circleopen|...")
    r.add_argument("--aspect", choices=list(ASPECTS), help="9:16 Short/Reel, 16:9 YouTube, 1:1 or 4:5 feed")
    r.add_argument("--resolution", help="e.g. 1080x1920 or 720x1280")
    r.add_argument("--fps", type=int)
    r.add_argument("--encoder", dest="video_encoder", help="libx264|h264_videotoolbox|h264_nvenc|auto")
    r.add_argument("--no-music", action="store_true", help="skip background music")
    u = p.add_argument_group("publishing")
    u.add_argument("--no-upload", action="store_true", help="render only, keep the MP4")
    u.add_argument("--privacy", help="public|unlisted|private")
    u.add_argument("--publish-times", help="schedule slots, e.g. 09:00,14:00,19:00")
    p.add_argument("--env-file", help="load settings from this file (one per channel)")
    p.add_argument("-v", "--verbose", action="store_true")


def build_settings(args: argparse.Namespace) -> Settings:
    load_env(getattr(args, "env_file", None))
    s = Settings.from_env()
    ov = {k: getattr(args, k, None) for k in (
        "style", "language", "target_seconds", "llm_provider", "llm_model", "tts_engine", "tts_voice",
        "tts_voice_b", "caption_style", "caption_position", "color_grade", "transition", "fps", "video_encoder",
        "privacy")}
    if getattr(args, "niche", None):
        ov["niches"] = args.niche
    if getattr(args, "visuals", None):
        ov["visual_sources"] = [v.strip().lower() for v in args.visuals.split(",") if v.strip()]
    if getattr(args, "aspect", None):
        ov["resolution"] = aspect_resolution(args.aspect)
    if getattr(args, "resolution", None):
        ov["resolution"] = parse_resolution(args.resolution)
    if getattr(args, "no_review", False):
        ov["script_review"] = "off"
    if getattr(args, "also_lang", None):
        ov["also_languages"] = [x.strip().lower() for x in args.also_lang.split(",") if x.strip()]
    if getattr(args, "no_music", False):
        ov["music_volume"] = 0.0
    if getattr(args, "no_upload", False):
        ov["upload"] = False
    if getattr(args, "publish_times", None):
        ov["publish_times"] = [t.strip() for t in args.publish_times.split(",") if t.strip()]
    s = s.with_overrides(**ov)
    if s.target_seconds:
        s.target_seconds = max(10, min(170, s.target_seconds))
    return s


# ------------------------------------------------------------------------------------------ commands
def cmd_run(args, s: Settings) -> int:
    from .pipeline import Studio
    if args.batch:
        s.batch_size = args.batch
    if args.workers:
        s.workers = args.workers
    if args.delay is not None:
        s.batch_delay = args.delay
    produced = Studio(s).autopilot(count=args.count, once=args.once, topic=args.topic, source=args.source)
    return 0 if produced or not (args.count or args.once) else 1


def cmd_make(args, s: Settings) -> int:
    from .pipeline import Studio
    studio = Studio(s)
    ok = 0
    for _ in range(max(1, args.count or 1)):
        r = studio.make(args.topic, source=args.source, script_file=args.script, url=args.url,
                        document=args.from_file)
        for x in [r, *r.variants]:
            ok += x.ok
            print_result(x)
    return 0 if ok else 1


def print_result(r) -> None:
    if not r.ok:
        print(f"\n✘ {r.language + ' ' if r.language else ''}failed: {r.error}")
        return
    score = f"\n  retention score: {r.score}/100" if r.score is not None else ""
    print(f"\n✔ {r.title}\n  folder: {r.folder}\n  status: {r.status}{score}"
          + (f"\n  https://youtube.com/shorts/{r.youtube_id}" if r.youtube_id else ""))


def cmd_demo(args, s: Settings) -> int:
    from .pipeline import Studio
    s = s.with_overrides(offline=True, upload=False)
    print("Demo: offline script + free neural voice + generated backgrounds. No API keys used.\n")
    r = Studio(s).make(args.topic, style=s.style if s.style != "auto" else None)
    if r.ok:
        print(f"\n✔ Demo video: {r.video}\n  (cover.jpg, captions.srt and metadata.json are next to it)")
        return 0
    print(f"\n✘ Demo failed: {r.error}")
    return 1


def cmd_upload(args, s: Settings) -> int:
    from .pipeline import Studio
    studio = Studio(s)
    if args.pending:
        n = studio.flush_queue(include_rendered=True)
        print(f"Uploaded {n} video(s). Remaining today: {max(0, studio.quota_left())}")
        return 0
    if args.id:
        return 0 if studio.upload_record(args.id) in ("uploaded", "scheduled") else 1
    print("Use --pending (everything not yet uploaded) or --id N (see `history`).")
    return 2


def cmd_auth(args, s: Settings) -> int:
    from . import youtube
    youtube.get_credentials(s, interactive=True, extra_scopes=youtube.auth_scopes(s))
    print(f"✔ YouTube authorized. Token saved to {s.token_file}")
    return 0


def cmd_history(args, s: Settings) -> int:
    from .history import History
    h = History(s.data_path / "history.db")
    rows = h.recent(args.limit)
    if not rows:
        print("No videos yet.")
        return 0
    print(f"{'ID':>4}  {'CREATED':19}  {'STATUS':9}  TITLE")
    for r in rows:
        link = f"  https://youtube.com/shorts/{r['youtube_id']}" if r["youtube_id"] else ""
        print(f"{r['id']:>4}  {r['created_at'][:19]:19}  {r['status']:9}  {r['title']}{link}")
    print("\n" + ", ".join(f"{k}: {v}" for k, v in h.stats().items()))
    return 0


def cmd_providers(args, s: Settings) -> int:
    from .llm import PRESETS, _key_for, ollama_models, ollama_url
    from .utils import http

    def running(name: str) -> bool:
        if name == "ollama":
            return ollama_models(ollama_url()) is not None
        try:
            return http().get(PRESETS[name].base_url + "/models", timeout=1.5).ok
        except Exception:
            return False

    print(f"{'PROVIDER':11} {'READY':8} {'DEFAULT MODEL':42} KEY")
    for name, p in PRESETS.items():
        ready = ("running" if running(name) else "off") if p.local else ("yes" if _key_for(p, s) else "-")
        keys = " / ".join(p.key_envs) or "(none)"
        print(f"{name:11} {ready:8} {p.default_model or '(LLM_MODEL)':42} {keys}")
    print("\nPick with LLM_PROVIDER / --provider and LLM_MODEL / --model. Any model the provider offers works.")
    return 0


def cmd_voices(args, s: Settings) -> int:
    from .tts import list_edge_voices
    voices = list_edge_voices(args.lang or s.language)
    for v in voices:
        print(f"{v['ShortName']:40} {v['Gender']:7} {v['Locale']}")
    print(f"\n{len(voices)} voices. Use one with TTS_VOICE=<name> or --voice <name>.")
    return 0


def cmd_doctor(args, s: Settings) -> int:
    from .doctor import checks
    print(f"PurffleShorts {__version__} — environment check\n")
    results = checks(s)
    for c in results:
        mark = {True: "✔", False: "✘", None: "•"}[c["ok"]]
        print(f" {mark} {c['label']}{': ' + c['detail'] if c['detail'] else ''}")
    ok = all(c["ok"] is not False for c in results)
    print("\nAll good." if ok else "\nFix the ✘ items above, then run again.")
    return 0 if ok else 1


def cmd_studio(args, s: Settings) -> int:
    from .studio import serve
    serve(s, host=args.host, port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_plan(args, s: Settings) -> int:
    from . import analytics
    from .pipeline import Studio
    from .planner import plan_ideas
    studio = Studio(s)
    insights = analytics.insights(studio.history) if s.learn_from_stats else ""
    ideas = plan_ideas(studio.llm, s, studio.history, args.count, args.niche, insights)
    for i in ideas:
        print(f"{i['id']:>4}  {i['style'] or 'auto':12} {i['subject']}\n      {i['notes']}")
    queued = len(studio.history.ideas("pending"))
    print(f"\n{len(ideas)} idea(s) added. {queued} waiting in the queue; `run` and `make` use them first.")
    return 0 if ideas else 1


def cmd_ideas(args, s: Settings) -> int:
    from .history import History
    h = History(s.data_path / "history.db")
    if args.add:
        print(f"Added idea #{h.add_idea(args.add, args.style or '')}")
        return 0
    if args.remove:
        h.delete_idea(args.remove)
        print(f"Removed idea #{args.remove}")
        return 0
    if args.clear:
        for i in h.ideas("pending"):
            h.delete_idea(i["id"])
        print("Queue cleared.")
        return 0
    rows = h.ideas("pending")
    if not rows:
        print("The idea queue is empty. Fill it with:  purffle-shorts plan --count 10")
        return 0
    for i in rows:
        print(f"{i['id']:>4}  {i['style'] or 'auto':12} {i['subject']}" + (f"\n      {i['notes']}" if i["notes"] else ""))
    return 0


def cmd_clip(args, s: Settings) -> int:
    from .clipper import make_clips
    from .pipeline import Studio
    results = make_clips(Studio(s), args.source, count=args.count, crop=args.crop,
                         min_seconds=args.min_seconds, max_seconds=args.max_seconds)
    for r in results:
        print_result(r)
    return 0 if any(r.ok for r in results) else 1


def cmd_stats(args, s: Settings) -> int:
    from .analytics import sync_stats
    from .history import History
    h = History(s.data_path / "history.db")
    n = sync_stats(s, h)
    rows = [r for r in h.recent(500) if r.get("views") is not None]
    if not rows:
        print("No stats yet." + ("" if n else " Upload some videos first, and set YOUTUBE_API_KEY or run `auth` "
                                         "again with LEARN_FROM_STATS=true."))
        return 0 if n or not h.live_video_ids() else 1
    rows.sort(key=lambda r: r["views"], reverse=True)
    print(f"{'VIEWS':>9} {'LIKES':>7} {'SCORE':>5}  TITLE")
    for r in rows[:args.limit]:
        score = r["score"] if r.get("score") is not None else "-"
        print(f"{r['views']:>9,} {r['likes'] or 0:>7,} {score:>5}  {r['title']}")
    return 0


def cmd_mcp(args, s: Settings) -> int:
    from .mcp_server import Server
    Server(s).serve()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="purffle-shorts", description="Autonomous AI YouTube Shorts studio.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("run", help="autopilot: make (and upload) Shorts on a loop")
    _common(r)
    r.add_argument("--count", type=int, help="stop after N successful videos")
    r.add_argument("--once", action="store_true", help="run a single batch, then exit")
    r.add_argument("--batch", type=int, help="videos per batch")
    r.add_argument("--workers", type=int, help="videos made in parallel")
    r.add_argument("--delay", type=int, help="seconds between batches")
    r.set_defaults(func=cmd_run)

    m = sub.add_parser("make", help="make one video now")
    _common(m)
    m.add_argument("--count", type=int, default=1)
    m.add_argument("--script", metavar="FILE",
                   help="render your own script JSON (e.g. an edited script.json) instead of asking the LLM")
    m.add_argument("--url", help="make the video from a web page (article, blog post, docs)")
    m.add_argument("--from-file", metavar="FILE", help="make the video from a .txt/.md/.html document")
    m.set_defaults(func=cmd_make)

    c = sub.add_parser("clip", help="cut a long video (file or URL) into captioned Shorts of its best moments")
    _common(c)
    c.add_argument("source", help="video file, or a URL (needs: pip install yt-dlp)")
    c.add_argument("--count", type=int, default=3, help="how many clips (default 3)")
    c.add_argument("--crop", choices=["center", "blur"], default="center",
                   help="center = fill the frame; blur = whole picture over a blurred copy")
    c.add_argument("--min-seconds", type=int, default=20)
    c.add_argument("--max-seconds", type=int, default=58)
    c.set_defaults(func=cmd_clip)

    pl = sub.add_parser("plan", help="let the AI plan a batch of video ideas into the queue")
    _common(pl)
    pl.add_argument("--count", type=int, default=10)
    pl.set_defaults(func=cmd_plan)

    ide = sub.add_parser("ideas", help="show or edit the idea queue")
    ide.add_argument("--add", metavar="SUBJECT", help="queue an idea")
    ide.add_argument("--style", help="format for --add")
    ide.add_argument("--remove", type=int, metavar="ID")
    ide.add_argument("--clear", action="store_true", help="remove every pending idea")
    ide.add_argument("--env-file")
    ide.set_defaults(func=cmd_ideas)

    stt = sub.add_parser("stats", help="refresh and show view counts of your uploaded videos")
    stt.add_argument("--limit", type=int, default=25)
    stt.add_argument("--env-file")
    stt.add_argument("-v", "--verbose", action="store_true")
    stt.set_defaults(func=cmd_stats)

    mc = sub.add_parser("mcp", help="run as an MCP server (stdio) for Claude Desktop, Claude Code, Cursor...")
    mc.add_argument("--env-file")
    mc.add_argument("-v", "--verbose", action="store_true")
    mc.set_defaults(func=cmd_mcp)

    d = sub.add_parser("demo", help="render a sample Short with no API keys")
    _common(d)
    d.set_defaults(func=cmd_demo)

    up = sub.add_parser("upload", help="upload rendered or queued videos")
    _common(up)
    up.add_argument("--pending", action="store_true", help="upload everything not yet on YouTube")
    up.add_argument("--id", type=int, help="upload one video by history id")
    up.set_defaults(func=cmd_upload)

    for name, func, helptext in [("auth", cmd_auth, "connect your YouTube channel (OAuth)"),
                                 ("doctor", cmd_doctor, "check ffmpeg, the LLM, voices, keys and YouTube setup"),
                                 ("providers", cmd_providers, "list supported LLM providers")]:
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--env-file")
        sp.add_argument("-v", "--verbose", action="store_true")
        sp.set_defaults(func=func)

    h = sub.add_parser("history", help="list videos made so far")
    h.add_argument("--limit", type=int, default=25)
    h.add_argument("--env-file")
    h.set_defaults(func=cmd_history)

    v = sub.add_parser("voices", help="list free neural voices (edge-tts)")
    v.add_argument("--lang", help="filter by language/locale, e.g. en, en-GB, hi")
    v.add_argument("--env-file")
    v.set_defaults(func=cmd_voices)

    st = sub.add_parser("studio", help="local web dashboard")
    _common(st)
    st.add_argument("--host", default="127.0.0.1")
    st.add_argument("--port", type=int, default=8765)
    st.add_argument("--no-browser", action="store_true")
    st.set_defaults(func=cmd_studio)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    home = os.getenv("PURFFLE_HOME")
    if home:
        os.chdir(Path(home).expanduser())
    try:
        s = build_settings(args)
    except ConfigError as e:
        print(f"Setting problem: {e}", file=sys.stderr)
        return 2
    # MCP speaks JSON-RPC on stdout, so its logs go to stderr.
    setup_logging(s, getattr(args, "verbose", False), sys.stderr if args.command == "mcp" else None)
    try:
        return args.func(args, s)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except Exception as e:  # clean one-line errors for config problems
        from .llm import LLMError
        from .youtube import NotAuthorized
        if isinstance(e, (LLMError, NotAuthorized)):
            log.error("%s", e)
            return 2
        raise
