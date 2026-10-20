from purffle_shorts.cli import build_parser, build_settings, main


def test_providers_command(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["providers"]) == 0
    out = capsys.readouterr().out
    assert "anthropic" in out and "ollama" in out


def test_overrides_from_flags(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = build_parser().parse_args(["make", "--lang", "es", "--visuals", "pexels,Pollinations", "--no-upload",
                                      "--resolution", "720x1280", "--duration", "500", "--no-music"])
    s = build_settings(args)
    assert s.language == "es" and s.visual_sources == ["pexels", "pollinations"]
    assert s.upload is False and s.resolution == (720, 1280)
    assert s.target_seconds == 170 and s.music_volume == 0.0


def test_live_line_shows_stage_percent_and_time_left():
    import io
    import logging

    from purffle_shorts import cli
    out = io.StringIO()
    line = cli.LiveLine(out)
    line.eta_fn = lambda: 75.0
    line("render", 50, "1080x1920")
    text = out.getvalue()
    assert "Render" in text and " 50%" in text and "1:15 left" in text and "1080x1920" in text
    handler = cli._Console(out)
    cli._Console.live = line
    try:
        handler.emit(logging.LogRecord("purffle", logging.INFO, __file__, 1, "Voice ready", None, None))
    finally:
        cli._Console.live = None
    after = out.getvalue()[len(text):]
    assert after.startswith("\r\033[K") and "Voice ready" in after and after.rstrip().endswith("1080x1920")
