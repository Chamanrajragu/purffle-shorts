import pytest

from purffle_shorts.config import Settings
from purffle_shorts.llm import extract_json
from purffle_shorts.script import SCRIPT_SCHEMA, build_prompt, normalize, offline_script


@pytest.mark.parametrize("text", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    'Sure! Here it is:\n{"a": 1}\nHope that helps.',
    '{"a": 1,}',
])
def test_extract_json_variants(text):
    assert extract_json(text) == {"a": 1}


def test_normalize_cleans_everything():
    data = {
        "topic": "Octopus", "title": '"Octopus Secrets" #shorts 🐙', "hook_text": "3 HEARTS?!",
        "scenes": [
            {"narration": "[Hook] Narrator: Octopuses have three hearts! 🐙 #facts", "search_query": "octopus",
             "image_prompt": "an octopus"},
            {"narration": "", "search_query": "x", "image_prompt": "x"},
            "Plain string scene works too.",
        ],
        "description": "Wow. #octopus", "hashtags": ["octopus", "#Ocean Life", "#shorts", "#octopus"],
        "tags": ["a" * 70] + [f"tag{i}" for i in range(200)], "category": "nonsense",
    }
    s = normalize(data, "octopus", "facts", "en")
    assert s.scenes[0].narration == "Octopuses have three hearts!"
    assert len(s.scenes) == 2
    assert s.title == "Octopus Secrets"
    assert s.hashtags[0] == "#shorts" and "#OceanLife" in s.hashtags
    assert len([h for h in s.hashtags if h.lower() == "#octopus"]) == 1
    assert sum(len(t) + 1 for t in s.tags) <= 500
    assert s.category == "education" and s.category_id == "27"
    assert "#" not in s.description


def test_normalize_merges_too_many_scenes():
    data = {"scenes": [{"narration": f"Sentence {i}.", "search_query": "q", "image_prompt": "p"} for i in range(20)]}
    s = normalize(data, "x", "facts", "en")
    assert len(s.scenes) == 12
    assert s.narration.count("Sentence") == 20


def test_offline_script_is_complete():
    s = offline_script("", Settings())
    assert s.title and len(s.scenes) >= 4 and s.hashtags[0] == "#shorts"


def test_prompt_mentions_language_and_length():
    system, user = build_prompt("space", "facts", Settings(language="es", target_seconds=30), ["Old title"])
    assert "Spanish" in user and "78 words" in user and "Old title" in user
    assert "JSON" in system
    assert set(SCRIPT_SCHEMA["required"]) >= {"title", "scenes", "hashtags"}
