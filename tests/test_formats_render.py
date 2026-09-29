"""Real ffmpeg renders of the 3.0 formats — chat stories, dialogues, 16:9, translations, clips. No network."""

import json
import subprocess

import pytest

from purffle_shorts import clipper, ffmpeg
from purffle_shorts import llm as L
from purffle_shorts import pipeline as P
from purffle_shorts.timing import Word, caption_chunks, scene_timeline

from .conftest import needs_ffmpeg


@pytest.fixture
def fast(settings):
    return settings.with_overrides(offline=True, tts_engine="silent", resolution=(360, 640), fps=24, music_volume=0.0)


@pytest.fixture
def spy_overlays(monkeypatch):
    calls = []
    real = P.build_overlays

    def spy(*a, **kw):
        calls.append(kw)
        return real(*a, **kw)
    monkeypatch.setattr(P, "build_overlays", spy)
    return calls


@needs_ffmpeg
def test_chat_story_renders_a_phone_screen(fast, spy_overlays):
    r = P.Studio(fast).make(style="chat")
    assert r.ok, r.error
    kw = spy_overlays[0]
    msgs = kw["chat"]
    assert len(msgs) == 10 and kw["contact"] == "Maya"
    assert [m.speaker for m in msgs[:2]] == ["A", "B"]
    assert all(b.start > a.start for a, b in zip(msgs, msgs[1:]))  # every message has its own moment
    meta = json.loads((r.folder / "metadata.json").read_text())
    assert meta["style"] == "chat" and meta["cast"] == ["Maya", "Me"]
    assert ffmpeg.probe(r.video)["duration"] > 20


@needs_ffmpeg
def test_dialogue_gets_speaker_tags(fast, spy_overlays):
    r = P.Studio(fast).make(style="dialogue")
    assert r.ok, r.error
    assert spy_overlays[0]["labels"] == {"A": "Alex", "B": "Sam"} and spy_overlays[0]["chat"] is None


@needs_ffmpeg
def test_landscape_video_is_not_a_short(fast):
    s = fast.with_overrides(resolution=(640, 360))
    r = P.Studio(s).make()
    assert r.ok, r.error
    assert r.video.name == "video.mp4" and not r.title.endswith("#shorts")
    info = ffmpeg.probe(r.video)
    assert (info["width"], info["height"]) == (640, 360)
    assert "#shorts" not in json.loads((r.folder / "metadata.json").read_text())["description"]


SCRIPT = {"topic": "cats", "title": "Why Cats Purr", "hook_text": "PURR POWER", "cast": [], "category": "pets",
          "scenes": [{"speaker": "A", "narration": f"Cats purr for reason number {i}.", "search_query": "cat",
                      "image_prompt": "cat"} for i in range(4)],
          "description": "Purring.", "hashtags": ["#cats"], "tags": ["cats"]}


class FakeLLM:
    calls: list = []

    def __init__(self, settings):
        self.providers, self.label = [object()], "fake:model"

    def complete_json(self, system, user, schema=None, max_tokens=4000):
        FakeLLM.calls.append(user[:40])
        if user.startswith("Review this"):
            return {"score": 64, "issues": ["The hook could be sharper"]}
        if user.startswith("Adapt this YouTube Short into Spanish"):
            return dict(SCRIPT, title="Por qué ronronean los gatos",
                        scenes=[dict(s, narration=f"Los gatos ronronean por la razón {i}.", search_query="gato")
                                for i, s in enumerate(SCRIPT["scenes"])])
        return json.loads(json.dumps(SCRIPT))


@needs_ffmpeg
def test_translated_copy_reuses_the_footage(fast, monkeypatch, tmp_path):
    FakeLLM.calls = []
    monkeypatch.setattr(P, "LLM", FakeLLM)
    searches = []
    real = P.Visuals.for_scenes
    monkeypatch.setattr(P.Visuals, "for_scenes", lambda self, *a: searches.append(a) or real(self, *a))
    s = fast.with_overrides(offline=False, visual_sources=["local"], media_dir=str(tmp_path / "none"))
    studio = P.Studio(s)
    r = studio.make("cats", languages=["es", "en"])
    assert r.ok, r.error
    assert r.score == 64 and len(r.variants) == 1  # "en" is the original's language
    v = r.variants[0]
    assert v.ok, v.error
    assert v.language == "es" and v.title.startswith("Por qué")
    assert len(searches) == 1                      # the copy searched for no new footage
    row = studio.history.get(v.record_id)
    assert row["parent_id"] == r.record_id and row["language"] == "es"
    assert json.loads((v.folder / "script.json").read_text())["scenes"][0]["search_query"] == "cat"


@needs_ffmpeg
def test_failed_video_returns_its_idea_to_the_queue(fast, monkeypatch):
    class Broken(FakeLLM):
        def complete_json(self, *a, **k):
            raise RuntimeError("model overloaded")
    monkeypatch.setattr(P, "LLM", Broken)
    studio = P.Studio(fast.with_overrides(offline=False))
    iid = studio.history.add_idea("why cats purr")
    r = studio.make()
    assert not r.ok and "overloaded" in r.error
    assert [i["id"] for i in studio.history.ideas("pending")] == [iid]


# ------------------------------------------------------------------ clipping long videos
@pytest.fixture
def long_video(tmp_path):
    path = tmp_path / "talk.mp4"
    subprocess.run([ffmpeg.ffmpeg_bin(), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=40",
                    "-f", "lavfi", "-i", "sine=f=220:d=40", "-shortest", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def _fake_transcript(total=40.0):
    words, t = [], 0.2
    text = ("This is the part where the story really begins. Nobody expected what happened next. "
            "The answer surprised everyone in the room. And that is why it matters today. ") * 3
    for w in text.split():
        words.append(Word(w, round(t, 2), round(t + 0.3, 2)))
        t += 0.62
    return [w for w in words if w.end < total]


@needs_ffmpeg
@pytest.mark.parametrize("crop", ["center", "blur"])
def test_clipper_cuts_captioned_vertical_clips(fast, monkeypatch, long_video, crop):
    monkeypatch.setattr(clipper, "transcribe", lambda video, work, settings: _fake_transcript())
    studio = P.Studio(fast)
    results = clipper.make_clips(studio, str(long_video), count=2, crop=crop, upload=False,
                                 min_seconds=8, max_seconds=14)
    assert len(results) == 2 and all(r.ok for r in results), [r.error for r in results]
    for r in results:
        info = ffmpeg.probe(r.video)
        assert (info["width"], info["height"]) == (360, 640) and 7 < info["duration"] < 16 and info["has_audio"]
        meta = json.loads((r.folder / "metadata.json").read_text())
        assert meta["source"] == "clip" and meta["clip_end"] > meta["clip_start"] and meta["score"] is None
        assert (r.folder / "captions.srt").read_text().strip()
    assert results[1].video != results[0].video
    assert not list(fast.out_path.glob(".clip-*"))  # scratch copy cleaned up


def test_clip_moments_snap_to_sentences_and_never_overlap():
    sents = clipper.sentences(_fake_transcript())

    class LLM:
        def complete_json(self, system, user, schema=None, max_tokens=4000):
            assert "[0.2-" in user
            return {"clips": [
                {"start": 0.1, "end": 11.0, "title": "A", "hook_text": "", "description": "", "hashtags": [],
                 "tags": [], "score": 70, "reason": "r"},
                {"start": 3.0, "end": 12.0, "title": "Overlaps A", "hook_text": "", "description": "",
                 "hashtags": [], "tags": [], "score": 95, "reason": "r"},
                {"start": 20.5, "end": 29.0, "title": "B", "hook_text": "", "description": "", "hashtags": [],
                 "tags": [], "score": 88, "reason": "r"},
                {"start": "x", "end": 1}]}
    plans = clipper.pick_clips(LLM(), sents, P.Settings(), count=3, min_s=8, max_s=14)
    assert [p.title for p in plans] == ["B", "A"]
    starts = {s.start for s in sents}
    assert all(p.start in starts and 8 <= p.duration <= 14 for p in plans)


# ------------------------------------------------------------------ timing with two speakers
def test_caption_chunks_never_mix_speakers():
    words = [Word("hi", 0, .2, "A"), Word("there", .25, .5, "A"), Word("hello", .6, .9, "B"), Word("you", .95, 1.2, "B")]
    chunks = caption_chunks(words, max_words=3)
    assert [c.speaker for c in chunks] == ["A", "B"] and [len(c.words) for c in chunks] == [2, 2]


def test_scene_timeline_from_line_starts_groups_short_messages():
    starts = [0.0, 1.0, 2.1, 3.0, 6.0, 7.2]
    tl = scene_timeline(["x"] * 6, [], 11.0, starts=starts, min_len=4.5)
    assert [(round(s.start, 1), round(s.end, 1)) for s in tl] == [(0.0, 6.0), (6.0, 11.0)]
    assert [s.index for s in tl] == [0, 4]                  # each shot uses its first message's footage
    tl = scene_timeline(["x"] * 6, [], 9.0, starts=starts, min_len=4.5)
    assert [(s.start, s.end) for s in tl] == [(0.0, 9.0)]   # a too-short last shot joins the previous one


@needs_ffmpeg
def test_translation_without_an_llm_keeps_the_original(fast, tmp_path, monkeypatch):
    monkeypatch.setattr(L, "_ollama_up", lambda url: False)  # even if Ollama runs on this machine
    f = tmp_path / "s.json"
    f.write_text(json.dumps(SCRIPT))
    s = fast.with_overrides(offline=False)  # no key is configured in tests
    r = P.Studio(s).make(script_file=f, languages=["fr"])
    assert r.ok and r.video.exists()
    assert len(r.variants) == 1 and not r.variants[0].ok and "LLM" in r.variants[0].error
