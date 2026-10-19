"""Two-speaker scripts, the Script Doctor and translation — with fake LLMs, no network."""

import pytest

from purffle_shorts.config import Settings
from purffle_shorts.script import (
    Script,
    build_prompt,
    lint_script,
    normalize,
    offline_script,
    review_script,
    rubric_score,
    scene_plan,
    script_from_data,
    translate_script,
)


class FakeLLM:
    label = "fake:model"

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def complete_json(self, system, user, schema=None, max_tokens=4000, temperature=None):
        self.calls.append({"system": system, "user": user, "schema": schema, "temperature": temperature})
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
    assert llm.calls[0]["schema"]["required"] == ["rubric", "issues", "script"]
    assert all(c["temperature"] == 0.2 for c in llm.calls)  # grading is repeatable


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


def test_reddit_story_is_one_narrator_with_handles():
    data = {"title": "t", "cast": ["pettyrevenge", "quiet otter"], "scenes": _scenes(6, speakers="AB")}
    s = normalize(data, "x", "reddit", "en")
    assert s.cast == ["r/pettyrevenge", "u/quiet_otter"]
    assert {sc.speaker for sc in s.scenes} == {"A"} and not s.multi_speaker
    assert normalize({"title": "t", "scenes": _scenes(5)}, "x", "reddit", "en").cast == ["r/stories", "u/throwaway"]
    system, user = build_prompt("a lost dog", "reddit", Settings(), [])
    assert "post title" in user and "u/" in user


def test_reddit_translation_keeps_the_handles():
    src = normalize({"title": "t", "cast": ["r/confessions", "u/otter"], "scenes": _scenes(4)}, "x", "reddit", "en")
    reply = {"title": "Hola", "cast": ["r/confesiones", "u/nutria"], "scenes": _scenes(4)}
    assert translate_script(FakeLLM(reply), src, "es").cast == ["r/confessions", "u/otter"]


def test_offline_reddit_story():
    s = offline_script("", Settings(), "reddit")
    assert s.style == "reddit" and s.cast == ["r/confessions", "u/quiet_otter22"]
    assert s.scenes[0].narration.startswith("Am I wrong") and len(s.scenes) == 8


RUBRIC_HIGH = {"hook": 9, "curiosity": 8, "pacing": 8, "specificity": 8, "payoff": 8, "accuracy": 9}
RUBRIC_LOW = {"hook": 4, "curiosity": 5, "pacing": 5, "specificity": 4, "payoff": 5, "accuracy": 7}


def _better(title="Better"):
    return {"title": title, "hook_text": "WOW", "cast": [], "scenes": _scenes(5, 9), "description": "d",
            "hashtags": ["#cats"], "tags": ["cats"], "category": "pets"}


def test_rubric_is_a_weighted_score():
    assert rubric_score(RUBRIC_HIGH) == 84
    assert rubric_score({k: 10 for k in RUBRIC_HIGH}) == 100
    assert rubric_score({"hook": 10}) == 65  # missing parts count as average (5)
    assert rubric_score("nonsense") is None


def test_the_stored_score_belongs_to_the_script_that_is_used():
    replies = iter([{"rubric": RUBRIC_LOW, "issues": ["Weak hook"], "script": _better()},   # review the draft
                    {"rubric": RUBRIC_HIGH, "issues": ["Ending could be punchier"]}])      # grade the rewrite
    llm = FakeLLM(lambda user: next(replies))
    out = review_script(llm, _draft(), Settings(target_seconds=16))
    assert out.title == "Better" and out.score == 84 and out.rubric["hook"] == 9
    assert out.review[0] == "Ending could be punchier"  # what is still weak in the final script
    assert llm.calls[1]["schema"]["required"] == ["rubric", "issues"]


def test_a_rewrite_that_scores_lower_is_thrown_away():
    replies = iter([{"rubric": RUBRIC_HIGH, "issues": ["Minor"], "script": _better("Worse")},
                    {"rubric": RUBRIC_LOW, "issues": ["Lost the hook"]}])
    out = review_script(FakeLLM(lambda user: next(replies)), _draft(), Settings(target_seconds=16))
    assert out.title == "Draft" and out.score == 84


def test_extra_rounds_until_the_target_score():
    replies = iter([{"rubric": RUBRIC_LOW, "issues": ["a"], "script": _better("Round 1")},
                    {"rubric": {**RUBRIC_LOW, "hook": 7}, "issues": ["b"]},                 # 59 < target
                    {"rubric": {**RUBRIC_LOW, "hook": 7}, "issues": ["b"], "script": _better("Round 2")},
                    {"rubric": RUBRIC_HIGH, "issues": []}])                                 # 84 >= 80: stop
    llm = FakeLLM(lambda user: next(replies))
    out = review_script(llm, _draft(), Settings(target_seconds=16, script_review_rounds=3))
    assert out.title == "Round 2" and out.score == 84 and len(llm.calls) == 4


def test_review_prompt_carries_the_automatic_checks():
    llm = FakeLLM({"rubric": RUBRIC_HIGH, "issues": []})
    hook = "Hey guys, welcome back to the channel, today we are going to talk about something really cool."
    draft = normalize({"title": "D", "scenes": [{"narration": hook, "search_query": "x"}] + _scenes(3)},
                      "cats", "facts", "en")
    review_script(llm, draft, Settings(script_review="score", target_seconds=16))
    user = llm.calls[0]["user"]
    assert "Automatic checks already found" in user and "greeting" in user and "first spoken sentence" in user


def test_lint_finds_the_obvious_problems():
    script = normalize({"title": "T", "scenes": [
        {"narration": "Hello and welcome, this is a video about cats and the things cats really do.",
         "search_query": "cat"},
        {"narration": "Cats sleep. Cats basically sleep a lot, really, just sleep, actually.", "search_query": "cat"},
    ]}, "pets", "facts", "en")
    found = " ".join(lint_script(script, Settings(target_seconds=40)))
    assert "greeting" in found and "call to action" in found and "filler" in found
    assert "No concrete number" in found and "words for a 40-second video" in found
    good = normalize({"title": "T", "scenes": [
        {"narration": "Cats sleep sixteen hours a day.", "search_query": "cat"},
        {"narration": "Which fact surprised you? Follow for more.", "search_query": "cat"},
    ]}, "pets", "facts", "en")
    assert not [c for c in lint_script(good, Settings(target_seconds=5)) if "call to action" in c or "number" in c]


def test_lint_judges_the_opening_sentence_and_accepts_a_closing_question():
    script = normalize({"title": "T", "scenes": [
        {"narration": "Octopus blood is blue. It carries oxygen with copper instead of iron, which works far "
                      "better in cold water with little oxygen.", "search_query": "octopus"},
        {"narration": "What's the weirdest animal fact you've heard?", "search_query": "ocean"},
    ]}, "octopus", "facts", "en")
    found = " ".join(lint_script(script, Settings(target_seconds=10)))
    assert "first spoken sentence" not in found  # "Octopus blood is blue." is 4 words
    assert "call to action" not in found         # a question invites comments
