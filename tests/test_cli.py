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
