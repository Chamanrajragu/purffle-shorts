"""Web pages, documents, RSS feeds and the planner's idea queue as topic sources."""

import pytest

from purffle_shorts import topics as T
from purffle_shorts.config import Settings
from purffle_shorts.history import History
from purffle_shorts.planner import plan_ideas

ARTICLE = """<html><head><title>Why Flamingos Are Pink | Nature Blog</title>
<meta property="og:title" content="Why Flamingos Are Pink"></head><body>
<nav><p>Home About Contact and a long navigation paragraph that should be skipped entirely.</p></nav>
<article><h1>Why flamingos are pink</h1>
<p>Flamingos are born grey. Their pink colour comes from carotenoid pigments in the algae and shrimp they eat.</p>
<p>A flamingo that stops eating those foods slowly fades back towards white over several months.</p>
<script>var tracking = "not article text at all, please ignore this";</script>
<ul><li>Zoos add canthaxanthin to the birds' food so they stay pink in captivity.</li></ul></article>
<footer><p>Copyright notice and other footer text that is not part of the article.</p></footer></body></html>"""


class Resp:
    def __init__(self, text="", status=200):
        self.text, self.status_code = text, status
        self.content = text.encode()


class Session:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url, params=None, headers=None, timeout=None):
        return Resp(self.pages[url])


def test_extract_article_keeps_the_story_only():
    title, text = T.extract_article(ARTICLE)
    assert title == "Why Flamingos Are Pink"
    assert "carotenoid" in text and "canthaxanthin" in text
    assert "navigation" not in text and "tracking" not in text and "Copyright" not in text


def test_from_url(monkeypatch):
    monkeypatch.setattr(T, "http", lambda: Session({"https://blog.example/flamingos": ARTICLE}))
    t = T.from_url("https://blog.example/flamingos")
    assert t.source == "url" and t.subject == "Why Flamingos Are Pink" and "carotenoid" in t.context
    with pytest.raises(ValueError):
        T.from_url("file:///etc/passwd")


def test_from_document(tmp_path):
    f = tmp_path / "notes.md"
    f.write_text("# The Great Emu War\n\nIn 1932 Australia sent soldiers with machine guns against emus. The emus won.")
    t = T.from_document(f)
    assert t.subject == "The Great Emu War" and "emus won" in t.context
    (tmp_path / "tiny.txt").write_text("hi")
    with pytest.raises(ValueError):
        T.from_document(tmp_path / "tiny.txt")


RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Election results are in</title><description>Voters decided.</description><link>https://n/1</link></item>
<item><title>Octopus caught using tools</title><description>&lt;p&gt;Researchers filmed an octopus &lt;b&gt;carrying&lt;/b&gt; shells.&lt;/p&gt;</description><link>https://n/2</link></item>
<item><title>Bees can count</title><description>Up to four.</description><link>https://n/3</link></item>
</channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Tardigrades survive space</title><summary>They were exposed to vacuum.</summary><link href="https://a/1"/></entry>
</feed>"""


def test_rss_skips_sensitive_and_used_items(monkeypatch, tmp_path):
    h = History(tmp_path / "h.db")
    monkeypatch.setattr(T, "http", lambda: Session({"https://feed/rss": RSS}))
    s = Settings(rss_feeds=["https://feed/rss"])
    t = T.from_rss(s, h)
    assert t.subject == "Octopus caught using tools" and t.context == "Researchers filmed an octopus carrying shells."
    h.mark_topic(t.key)
    assert T.from_rss(s, h).subject == "Bees can count"


def test_atom_feeds_work(monkeypatch, tmp_path):
    monkeypatch.setattr(T, "http", lambda: Session({"https://feed/atom": ATOM}))
    t = T.from_rss(Settings(rss_feeds=["https://feed/atom"]), History(tmp_path / "h.db"))
    assert t.subject == "Tardigrades survive space" and t.key == "rss:https://a/1"


def test_idea_queue_comes_first_and_can_be_released(tmp_path):
    h = History(tmp_path / "h.db")
    first = h.add_idea("why cats purr", "explainer", "they purr when hurt too")
    h.add_idea("second idea")
    t = T.pick_topic(Settings(), h)
    assert t.source == "idea" and t.idea_id == first and t.style == "explainer"
    assert t.subject == "why cats purr (angle: they purr when hurt too)"
    assert [i["subject"] for i in h.ideas("pending")] == ["second idea"]
    h.release_idea(first)
    assert len(h.ideas("pending")) == 2
    # An explicit source skips the queue.
    assert T.pick_topic(Settings(niches=["space"]), h, source="niche").source == "niche"


def test_planner_saves_unique_ideas(tmp_path):
    h = History(tmp_path / "h.db")
    h.add_video(title="Why Cats Purr", status="uploaded")

    class LLM:
        def complete_json(self, system, user, schema=None, max_tokens=4000):
            assert "Why Cats Purr" in user and "3 YouTube Shorts" in user
            return {"ideas": [
                {"subject": "why cats purr", "style": "facts", "angle": "dup of a made video"},
                {"subject": "The emu war of 1932", "style": "story", "angle": "Australia lost to birds"},
                {"subject": "the emu war of 1932", "style": "story", "angle": "duplicate"},
                {"subject": "Mantis shrimp punches", "style": "not-a-format", "angle": "fastest punch"},
            ]}
    ideas = plan_ideas(LLM(), Settings(), h, count=3, niches=["animals"])
    assert [i["subject"] for i in ideas] == ["The emu war of 1932", "Mantis shrimp punches"]
    assert ideas[1]["style"] == "" and len(h.ideas("pending")) == 2


REDDIT_FEED = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>TIFU by tipping my pizza driver $100</title>
<content type="html">&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;&lt;p&gt;I meant to tip ten dollars. I&amp;#39;m still
thinking about it.&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt; &amp;#32; submitted by &amp;#32; &lt;a href="x"&gt;
/u/someone &lt;/a&gt; &lt;br/&gt; &lt;span&gt;&lt;a href="y"&gt;[link]&lt;/a&gt;&lt;/span&gt;</content></entry>
<entry><title>a comment</title><content type="html">not the post</content></entry></feed>"""


def test_reddit_post_link_is_read_from_its_feed(monkeypatch):
    feed = "https://www.reddit.com/r/tifu/comments/abc123/.rss"
    monkeypatch.setattr(T, "http", lambda: Session({feed: REDDIT_FEED}))
    t = T.from_url("https://www.reddit.com/r/tifu/comments/abc123/tifu_by_tipping/?utm_source=share")
    assert t.subject == "TIFU by tipping my pizza driver $100" and t.style == "reddit"
    assert "I'm still thinking about it." in t.context
    assert "submitted by" not in t.context and "not the post" not in t.context
