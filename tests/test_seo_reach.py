"""Reach: real YouTube searches for topics and keywords, localised titles, caption tracks, and the new
options in the CLI, Studio and MCP server."""

import json
import wave

import pytest

from purffle_shorts import cli, mcp_server, seo, topics, tts
from purffle_shorts import pipeline as P
from purffle_shorts import youtube as Y
from purffle_shorts.config import Settings
from purffle_shorts.script import localize_metadata, offline_script

from .conftest import needs_ffmpeg
from .test_pipeline_online import SCRIPT, FakeLLM, clip, online  # noqa: F401  (fixtures)

REAL_SUGGESTIONS = seo.suggestions  # conftest switches the network call off for every test


class _Resp:
    def __init__(self, data, code=200):
        self._data, self.status_code = data, code

    def json(self):
        return self._data


def test_suggestions_parse_youtube_autocomplete(monkeypatch):
    seen = {}

    class Session:
        def get(self, url, params=None, timeout=None):
            seen.update(params)
            return _Resp(["octopus", ["octopus facts", "octopus hearts", 7, ""], [], {}])
    monkeypatch.setattr(seo, "http", lambda: Session())
    assert REAL_SUGGESTIONS("octopus", "pt-BR", "BR") == ["octopus facts", "octopus hearts"]
    assert seen["ds"] == "yt" and seen["hl"] == "pt" and seen["gl"] == "BR"

    class Broken:
        def get(self, *a, **k):
            raise OSError("offline")
    monkeypatch.setattr(seo, "http", lambda: Broken())
    assert REAL_SUGGESTIONS("octopus") == []


def _fake(monkeypatch, table):
    monkeypatch.setattr(seo, "suggestions", lambda q, *a, **k: table.get(q, []))


def test_search_phrases_keep_real_on_topic_searches(monkeypatch):
    _fake(monkeypatch, {
        "the human body": ["the human body", "the human body explained", "the human body in hindi",
                           "the human body documentary", "human body facts"],
        "why do human": ["why do humans have tailbones", "why do human bodybuilders tan"],
        "why is human": ["why is human body temperature 37"],
    })
    out = seo.search_phrases("the human body")
    assert "the human body explained" in out and "why is human body temperature 37" in out
    assert "the human body in hindi" not in out and "the human body documentary" not in out
    assert "why do humans have tailbones" not in out          # shares only one of the subject's two words
    assert "the human body" not in out                        # the seed itself adds nothing


def test_question_topics_rank_by_the_niche_and_skip_used_ones(monkeypatch):
    _fake(monkeypatch, {
        "why is ocean": ["why is ocean water salty", "why is ocean blue"],
        "how does ocean": ["how does ocean mysteries get solved", "how does oceanic work"],
        "how do mysteries": ["how do mysteries get solved"],
    })
    monkeypatch.setattr(seo.random, "shuffle", lambda x: None)
    qs = seo.question_topics("ocean mysteries", lambda p: p == "why is ocean blue")
    assert qs[0] == "how does ocean mysteries get solved"     # shares both words
    assert "why is ocean water salty" in qs and "why is ocean blue" not in qs
    assert all("oceanic" not in q for q in qs)                # whole words only
    block = seo.keywords_block(qs[:2])
    assert "Real searches people type into YouTube" in block and qs[0] in block
    assert seo.keywords_block([]) == ""


def test_search_topic_source_hands_the_questions_to_the_writer(settings, monkeypatch, tmp_path):
    from purffle_shorts.history import History
    monkeypatch.setattr(seo, "question_topics", lambda niche, used, *a, **k: ["why is ocean water salty",
                                                                             "how do ocean waves work"])
    h = History(tmp_path / "h.db")
    t = topics.from_search(settings.with_overrides(niches=["ocean mysteries"]), h)
    assert t.source == "search" and t.subject == "ocean mysteries" and t.key == "search:why is ocean water salty"
    assert t.keywords == ["why is ocean water salty", "how do ocean waves work"]
    assert "why is ocean water salty" in t.context and "exact words in the title" in t.context


class CaptureLLM(FakeLLM):
    prompts: list = []

    def complete_json(self, system, user, schema=None, max_tokens=4000, temperature=None):
        CaptureLLM.prompts.append(user)
        if "Translate this YouTube Short's title" in user:
            return {"items": [{"language": "es", "title": "Por qué el pulpo tiene tres corazones #pulpo",
                               "description": "Tres corazones. #shorts"},
                              {"language": "xx", "title": "nope", "description": ""}]}
        return json.loads(json.dumps(SCRIPT))


@needs_ffmpeg
def test_keywords_and_localised_metadata_reach_the_upload(online, monkeypatch):  # noqa: F811
    s, _ = online
    CaptureLLM.prompts = []
    monkeypatch.setattr(P, "LLM", CaptureLLM)
    monkeypatch.setattr(seo, "search_phrases", lambda subject, *a, **k: ["why do octopuses have three hearts"])
    bodies = []
    monkeypatch.setattr(P.youtube, "upload", lambda settings, video, body: bodies.append(body) or {"id": "v9"})
    captions = []
    monkeypatch.setattr(P.youtube, "upload_captions", lambda *a: captions.append(a) or True)
    s = s.with_overrides(localize_metadata=["es", "en"], upload_captions=True, script_review="off")
    r = P.Studio(s).make("octopus hearts")
    assert r.ok, r.error
    assert "why do octopuses have three hearts" in CaptureLLM.prompts[0]
    meta = json.loads((r.folder / "metadata.json").read_text())
    assert meta["search_keywords"] == ["why do octopuses have three hearts"]
    es = meta["localizations"]["es"]
    assert es["title"] == "Por qué el pulpo tiene tres corazones #shorts" and "#octopus" in es["description"]
    assert set(meta["localizations"]) == {"es"}                       # unknown and same-language codes dropped
    assert bodies[0]["localizations"]["es"]["title"].startswith("Por qué")
    assert captions and captions[0][1] == "v9" and captions[0][2].name == "captions.srt"


def test_localize_metadata_needs_other_languages(settings):
    script = offline_script("demo", settings)
    assert localize_metadata(None, script, ["en"]) == {}       # no call at all for the video's own language


def test_build_body_and_upload_send_localizations(settings, tmp_path, monkeypatch):
    body = Y.build_body(settings, "Title", "d", [], "27", "en",
                        localizations={"es": {"title": "Título", "description": "d"}, "en": {"title": "x"}})
    assert body["localizations"] == {"es": {"title": "Título", "description": "d"}}
    assert "localizations" not in Y.build_body(settings, "Title", "d", [], "27", "en")
    parts = []

    class Insert:
        def next_chunk(self):
            return None, {"id": "abc"}

    class Videos:
        def insert(self, part, body, media_body):
            parts.append(part)
            return Insert()

    class YT:
        def videos(self):
            return Videos()
    monkeypatch.setattr(Y, "service", lambda *a, **k: YT())
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0" * 100)
    assert Y.upload(settings, video, body)["id"] == "abc"
    assert parts == ["snippet,status,localizations"]


def test_caption_upload_needs_the_extra_permission(settings, tmp_path, monkeypatch, caplog):
    srt = tmp_path / "captions.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    assert Y.SCOPE_CAPTIONS in Y.auth_scopes(settings.with_overrides(upload_captions=True))
    assert Y.SCOPE_CAPTIONS not in Y.auth_scopes(settings)

    def not_authorized(*a, **k):
        raise Y.NotAuthorized("needs auth")
    monkeypatch.setattr(Y, "service", not_authorized)
    assert Y.upload_captions(settings, "vid", srt, "en") is False
    assert "run `purffle-shorts auth`" in caplog.text
    sent = []

    class Captions:
        def insert(self, part, body, media_body):
            sent.append(body)

            class Req:
                def execute(self):
                    return {"id": "c1"}
            return Req()

    class YT:
        def captions(self):
            return Captions()
    monkeypatch.setattr(Y, "service", lambda *a, **k: YT())
    assert Y.upload_captions(settings, "vid", srt, "es", "Spanish") is True
    assert sent[0]["snippet"] == {"videoId": "vid", "language": "es", "name": "Spanish", "isDraft": False}


def test_new_settings_are_read_from_the_environment(monkeypatch):
    for k, v in {"SOUND_EFFECTS": "false", "SFX_VOLUME": "0.4", "CAPTION_EMPHASIS": "off",
                 "BACKGROUND_VIDEO": "media/backgrounds", "BACKGROUND_LAYOUT": "split", "CLIP_JUMP_CUTS": "no",
                 "CLIP_MAX_PAUSE": "0.05", "CLIP_ZOOM": "0", "LOCALIZE_METADATA": "es, pt-BR, bad code, hi",
                 "UPLOAD_CAPTIONS": "yes", "SEO_KEYWORDS": "false"}.items():
        monkeypatch.setenv(k, v)
    s = Settings.from_env()
    assert (s.sound_effects, s.sfx_volume, s.caption_emphasis) == (False, 0.4, False)
    assert (s.background_video, s.background_layout) == ("media/backgrounds", "split")
    assert (s.clip_jump_cuts, s.clip_max_pause, s.clip_zoom) == (False, 0.2, False)
    assert s.localize_metadata == ["es", "pt-BR", "hi"] and s.upload_captions and not s.seo_keywords


def test_cli_flags_for_the_new_options(monkeypatch):
    p = cli.build_parser()
    a = p.parse_args(["make", "--background", "bg.mp4", "--layout", "split", "--no-sfx"])
    s = cli.build_settings(a)
    assert (s.background_video, s.background_layout, s.sound_effects) == ("bg.mp4", "split", False)
    c = p.parse_args(["clip", "talk.mp4", "--prompt", "the jokes", "--no-jump-cuts", "--no-zoom"])
    s = cli.build_settings(c)
    assert c.prompt == "the jokes" and not s.clip_jump_cuts and not s.clip_zoom


def test_clip_results_print_a_virality_score(capsys):
    cli.print_result(P.Result(True, "Best bit", status="rendered", score=91, reason="opens on a bold claim"))
    out = capsys.readouterr().out
    assert "virality score: 91/100 (opens on a bold claim)" in out
    cli.print_result(P.Result(True, "Video", status="rendered", score=80))
    assert "retention score: 80/100" in capsys.readouterr().out


def test_mcp_tools_accept_the_new_options(settings):
    tools = {t["name"]: t["inputSchema"]["properties"] for t in mcp_server.TOOLS}
    assert {"background_video", "layout", "sound_effects"} <= set(tools["make_short"])
    assert {"prompt", "jump_cuts", "zoom"} <= set(tools["clip_video"])
    srv = mcp_server.Server(settings)
    s = srv._settings({"background_video": "bg.mp4", "layout": "split", "sound_effects": False, "zoom": False})
    assert (s.background_video, s.background_layout, s.sound_effects, s.clip_zoom) == ("bg.mp4", "split", False,
                                                                                         False)


def test_studio_overrides_and_background_list(settings, tmp_path, monkeypatch):
    from purffle_shorts import studio as ST
    bgs = tmp_path / "media" / "backgrounds"
    bgs.mkdir(parents=True)
    (bgs / "parkour.mp4").write_bytes(b"x")
    (bgs / "readme.txt").write_text("x")
    monkeypatch.setenv("STUDIO_TOKEN", "fixed-token")
    app = ST.StudioServer(settings.with_overrides(media_dir=str(tmp_path / "media")))
    try:
        assert app.token == "fixed-token"
        assert app.options()["backgrounds"] == [{"path": str(bgs / "parkour.mp4"), "name": "parkour.mp4"}]
        s = app.overrides({"background": str(bgs / "parkour.mp4"), "layout": "split", "sfx": False,
                           "emphasis": False, "jump_cuts": False, "zoom": False})
        assert (s.background_video, s.background_layout) == (str(bgs / "parkour.mp4"), "split")
        assert not (s.sound_effects or s.caption_emphasis or s.clip_jump_cuts or s.clip_zoom)
        s = app.overrides({"background": "/no/such/file.mp4", "layout": "diagonal", "sfx": "yes"})
        assert s.background_video == "" and s.background_layout == "full" and s.sound_effects is True
    finally:
        import logging
        root = logging.getLogger()
        for h in [h for h in root.handlers if isinstance(h, ST._JobLog)]:
            root.removeHandler(h)


@needs_ffmpeg
def test_whisper_gets_16k_float_samples_from_our_ffmpeg(tmp_path):
    pytest.importorskip("numpy")
    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(b"\x00\x10" * 2 * 48000)
    pcm = tts._pcm16k(path)
    assert pcm.dtype.name == "float32" and abs(len(pcm) - 16000) <= 2


def test_adult_searches_are_never_used():
    assert not seo.usable("test your gaydar quiz") and not seo.usable("naked mole rat sex")
    assert seo.usable("why do naked mole rats live so long")            # a classic animal topic stays
    assert seo.usable("why do octopuses have three hearts")


def test_planner_asks_for_true_checkable_ideas(settings):
    from purffle_shorts.planner import plan_prompt
    _, user = plan_prompt(settings, 5, ["health"], [])
    assert "true and checkable" in user and "miracle health" in user


def test_ordinary_words_do_not_trip_the_off_topic_filter():
    assert seo.usable("what was the manhattan project")
    assert seo.usable("how long do turtles live")
    assert not seo.usable("octopus live stream") and not seo.usable("octopus documentary")
