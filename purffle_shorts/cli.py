"""Command line: `purffle-shorts <command>` or `python -m purffle_shorts <command>`."""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from . import __version__
from .config import Settings, load_env, parse_resolution

log = logging.getLogger("purffle")


def setup_logging(settings: Settings, verbose: bool = False) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
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
    g.add_argument("--source", choices=["niche", "trending", "wikipedia", "reddit", "file"], help="topic source")
    g.add_argument("--niche", action="append", help="niche to pick topics from (repeatable)")
    g.add_argument("--style", help="facts|story|listicle|myth|quiz|motivational|news|explainer|auto")
    g.add_argument("--lang", dest="language", help="language code, e.g. en, es, hi, ta, fr, ja")
    g.add_argument("--duration", dest="target_seconds", type=int, help="target length in seconds (15-170)")
    g.add_argument("--provider", dest="llm_provider", help="LLM provider (see `providers`)")
    g.add_argument("--model", dest="llm_model", help="LLM model name")
    g.add_argument("--tts", dest="tts_engine", help="edge|openai|elevenlabs|kokoro|coqui|system|silent")
    g.add_argument("--voice", dest="tts_voice", help="voice name/id (comma list = rotate)")
    g.add_argument("--visuals", help="comma list: pexels,pixabay,local,openai-images,pollinations")
    r = p.add_argument_group("look & output")
    r.add_argument("--caption-style", help="bold|boxed|neon|clean|karaoke|minimal")
    r.add_argument("--caption-position", help="upper|center|lower")
    r.add_argument("--grade", dest="color_grade", help="none|vivid|cinematic|warm|cool|bw")
    r.add_argument("--transition", help="random|none|fade|slideup|circleopen|...")
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
        "caption_style", "caption_position", "color_grade", "transition", "fps", "video_encoder", "privacy")}
    if getattr(args, "niche", None):
        ov["niches"] = args.niche
    if getattr(args, "visuals", None):
        ov["visual_sources"] = [v.strip().lower() for v in args.visuals.split(",") if v.strip()]
    if getattr(args, "resolution", None):
        ov["resolution"] = parse_resolution(args.resolution)
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
        r = studio.make(args.topic, source=args.source)
        if r.ok:
            ok += 1
            print(f"\n✔ {r.title}\n  folder: {r.folder}\n  status: {r.status}"
                  + (f"\n  https://youtube.com/shorts/{r.youtube_id}" if r.youtube_id else ""))
        else:
            print(f"\n✘ failed: {r.error}")
    return 0 if ok else 1


def cmd_demo(args, s: Settings) -> int:
    from .pipeline import Studio
    s = s.with_overrides(offline=True, upload=False)
    print("Demo: offline script + free neural voice + generated backgrounds. No API keys used.\n")
    r = Studio(s).make(args.topic)
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
    youtube.get_credentials(s, interactive=True)
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
    from .llm import PRESETS, _key_for
    print(f"{'PROVIDER':11} {'READY':6} {'DEFAULT MODEL':42} KEY")
    for name, p in PRESETS.items():
        ready = "local" if p.local else ("yes" if _key_for(p, s) else "-")
        keys = " / ".join(p.key_envs) or "(none)"
        print(f"{name:11} {ready:6} {p.default_model or '(LLM_MODEL)':42} {keys}")
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
    from . import ffmpeg
    from .llm import LLMError, resolve_provider_name
    ok = True

    def line(good: bool | None, label: str, detail: str = ""):
        mark = {True: "✔", False: "✘", None: "•"}[good]
        print(f" {mark} {label}{': ' + detail if detail else ''}")

    print(f"PurffleShorts {__version__} — environment check\n")
    line(sys.version_info >= (3, 10), "Python", sys.version.split()[0])
    try:
        line(True, "ffmpeg", f"{ffmpeg.version()} ({ffmpeg.ffmpeg_bin()})")
        for flt in ("xfade", "sidechaincompress", "loudnorm", "zoompan"):
            if not ffmpeg.has_filter(flt):
                ok = False
                line(False, f"ffmpeg filter {flt}", "missing — update ffmpeg (6.0+ recommended)")
        line(True if ffmpeg.has_filter("ass") else None, "libass (complex-script captions)",
             "available" if ffmpeg.has_filter("ass") else "not in this ffmpeg build")
    except Exception as e:
        ok = False
        line(False, "ffmpeg", str(e))
    try:
        name = resolve_provider_name(s)
        line(True, "LLM", f"{name} (model: {s.llm_model or 'default'})")
    except LLMError as e:
        ok = False
        line(False, "LLM", str(e))
    line(True, "Voice", s.tts_engine + (f" / {s.tts_voice}" if s.tts_voice else ""))
    if s.tts_engine == "elevenlabs" and not s.elevenlabs_api_key:
        ok = False
        line(False, "ElevenLabs key", "ELEVENLABS_API_KEY missing")
    usable = 0
    for src in s.visual_sources:
        need = {"pexels": s.pexels_api_key, "pixabay": s.pixabay_api_key,
                "openai-images": s.openai_api_key}.get(src, "n/a")
        usable += bool(need)
        line(True if need and need != "n/a" else None, f"Visual source {src}",
             "key found" if need and need != "n/a" else ("no key needed" if need == "n/a" else "API key missing"))
    if not usable:
        ok = False
        line(False, "Footage", "no usable visual source — every scene would be an animated gradient")
    try:
        import edge_tts  # noqa: F401
        line(True, "edge-tts", "installed")
    except ImportError:
        line(s.tts_engine != "edge", "edge-tts", "not installed (pip install edge-tts)")
    from .render import pick_music
    m = pick_music(s)
    line(None, "Music", str(m) if m else f"none (add tracks to {s.music_dir}/)")
    if s.upload:
        cs = Path(s.client_secrets).exists()
        tok = Path(s.token_file).exists() or Path("token.pickle").exists()
        line(cs or tok, "YouTube OAuth client", s.client_secrets if cs else "credentials.json missing")
        line(tok if cs else None, "YouTube token", "found" if tok else "run: python -m purffle_shorts auth")
        line(None, "Publishing", f"{s.privacy}" + (f", scheduled at {', '.join(s.publish_times)}" if s.publish_times
                                                  else "") + f", max {s.daily_upload_limit}/day")
    else:
        line(None, "Upload", "disabled (UPLOAD=false)")
    print("\nAll good." if ok else "\nFix the ✘ items above, then run again.")
    return 0 if ok else 1


def cmd_studio(args, s: Settings) -> int:
    from .studio import serve
    serve(s, host=args.host, port=args.port, open_browser=not args.no_browser)
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
    m.set_defaults(func=cmd_make)

    d = sub.add_parser("demo", help="render a sample Short with no API keys")
    _common(d)
    d.set_defaults(func=cmd_demo)

    up = sub.add_parser("upload", help="upload rendered or queued videos")
    _common(up)
    up.add_argument("--pending", action="store_true", help="upload everything not yet on YouTube")
    up.add_argument("--id", type=int, help="upload one video by history id")
    up.set_defaults(func=cmd_upload)

    for name, func, helptext in [("auth", cmd_auth, "connect your YouTube channel (OAuth)"),
                                 ("doctor", cmd_doctor, "check ffmpeg, keys, fonts and YouTube setup"),
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
    s = build_settings(args)
    setup_logging(s, getattr(args, "verbose", False))
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
