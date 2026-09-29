"""Two-speaker scripts, the Script Doctor and translation — with fake LLMs, no network."""

import pytest

from purffle_shorts.config import Settings
from purffle_shorts.script import (
    Script,
    build_prompt,
    normalize,
    offline_script,
    review_script,
    scene_plan,
    script_from_data,
    translate_script,
)


class FakeLLM:
    label = "fake:model"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def complete_json(self, system, user, schema=None, max_tokens=4000):
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.error:
            raise self.error
        return self.reply(user) if callable(self.reply) else self.reply


def _scenes(n, words=8, speakers="A"):
    return [{"speaker": speakers[i % len(speakers)], "narration": " ".join(["word"] * words) + ".",
             "search_query": f"q{i}", "image_prompt": f"p{i}"} for i in range(n)]


def test_dialogue_keeps_speakers_and_fills_cast():
    s = normalize({"title": "T", "cast": ["Mia"], "scenes": _scenes(4, speakers="AB")}, "x", "dialogue", "en")
    assert [sc.speaker for sc in s.scenes] == ["A", "B", "A", "B"]
    assert s.cast == ["Mia", "Sam"] and s.multi_speaker
    assert s.speaker_name("B") == "Sam"


def test_single_narrator_formats_ignore_speakers():
    s = normalize({"title": "T", "cast": ["X", "Y"], "scenes": _scenes(4, speakers="AB")}, "x", "facts", "en")
    assert {sc.speaker for sc in s.scenes} == {"A"} and s.cast == [] and not s.multi_speaker


def test_chat_allows_more_scenes_and_merges_only_same_speaker():
    s = normalize({"scenes": _scenes(26, words=2, speakers="AB")}, "x", "chat", "en")
    assert len(s.scenes) == 26  # alternating speakers can't be merged
    s = normalize({"scenes": _scenes(26, words=2, speakers="A")}, "x", "chat", "en")
    assert len(s.scenes) == 20


def test_from_dict_ignores_unknown_and_missing_fields():
    d = offline_script("", Settings()).to_dict()
    d["future_field"] = 1
    d["scenes"][0]["extra"] = "x"
    del d["cast"]
    s = Script.from_dict(d)
    assert s.title and s.cast == [] and s.scenes[0].speaker == "A"


def test_script_from_data_detects_a_conversation():
    s = script_from_data({"title": "Chat", "scenes": _scenes(4, speakers="AB")}, Settings())
    assert s.style == "dialogue" and s.multi_speaker


def test_scene_plan_by_format():
    assert scene_plan("facts", 40) == (104, 7)
    assert scene_plan("chat", 40)[1] == 14
    assert scene_plan("dialogue", 40)[1] == 11


def test_prompt_carries_format_rules_and_channel_insights():
    _, user = build_prompt("cats", "chat", Settings(), [], insights="What performed best: X")
    assert "text message" in user and '"Me"' in user and "What performed best: X" in user
    _, user = build_prompt("cats", "facts", Settings(), [])
    assert 'speaker is always "A"' in user


def _draft(words=10, n=4):
    return normalize({"title": "Draft", "hook_text": "HOOK", "scenes": _scenes(n, words)}, "cats", "facts", "en")


def test_doctor_rewrite_is_used_when_sane():
    settings = Settings(target_seconds=16)  # 41-word target
    better = {"title": "Better", "hook_text": "WOW", "cast": [], "scenes": _scenes(5, 9), "description": "d",
              "hashtags": ["#cats"], "tags": ["cats"], "category": "pets"}
    llm = FakeLLM({"score": 91, "issues": ["Weak hook", "Scene 3 is vague"], "script": better})
    out = review_script(llm, _draft(), settings)
    assert out.title == "Better" and out.score == 91 and out.review[0] == "Weak hook"
    assert out.category == "pets" and out.style == "facts"
    assert llm.calls[0]["schema"]["required"] == ["score", "issues", "script"]


def test_doctor_rewrite_with_wrong_length_is_ignored():
    llm = FakeLLM({"score": 40, "issues": ["too long"], "script": {"title": "Bloated", "scenes": _scenes(30, 20)}})
    out = review_script(llm, _draft(), Settings(target_seconds=16))
    assert out.title == "Draft" and out.score == 40


def test_doctor_failure_never_fails_the_video():
    draft = _draft()
    assert review_script(FakeLLM(error=RuntimeError("503")), draft, Settings()) is draft
    assert draft.score is None


def test_doctor_score_only_and_off():
    llm = FakeLLM({"score": "77", "issues": []})
    out = review_script(llm, _draft(), Settings(script_review="score"))
    assert out.title == "Draft" and out.score == 77 and "script" not in llm.calls[0]["schema"]["properties"]
    off = FakeLLM({"score": 1})
    review_script(off, _draft(), Settings(script_review="off"))
    assert off.calls == []


def test_translation_keeps_footage_and_speakers():
    src = normalize({"title": "Hi", "cast": ["A1", "B1"], "scenes": _scenes(4, speakers="AB")}, "x", "dialogue", "en")

    def reply(user):
        assert "Spanish" in user and "EXACTLY 4 scenes" in user
        return {"title": "Hola", "hook_text": "HOLA", "cast": ["Ana", "Bea"], "category": "education",
                "scenes": [{"speaker": "A", "narration": f"frase {i}.", "search_query": "cambiado",
                            "image_prompt": "cambiado"} for i in range(4)],
                "description": "d", "hashtags": ["#hola"], "tags": ["hola"]}
    out = translate_script(FakeLLM(reply), src, "es")
    assert out.language == "es" and out.title == "Hola" and out.cast == ["Ana", "Bea"]
    assert [s.search_query for s in out.scenes] == ["q0", "q1", "q2", "q3"]
    assert [s.speaker for s in out.scenes] == ["A", "B", "A", "B"]


def test_translation_with_wrong_scene_count_is_rejected():
    src = _draft(n=4)
    with pytest.raises(ValueError, match="scenes"):
        translate_script(FakeLLM({"title": "x", "scenes": _scenes(3)}), src, "fr")


@pytest.mark.parametrize("style", ["dialogue", "chat"])
def test_offline_conversations_are_complete(style):
    s = offline_script("", Settings(), style)
    assert s.style == style and s.multi_speaker and len(s.cast) == 2 and len(s.scenes) >= 8
