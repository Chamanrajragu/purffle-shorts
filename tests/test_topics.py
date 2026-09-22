from purffle_shorts import topics as T
from purffle_shorts.config import Settings
from purffle_shorts.history import History

TRENDS = b"""<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss" version="2.0"><channel>
<item><title>celebrity dies</title><ht:news_item><ht:news_item_title>Star dies at 80</ht:news_item_title></ht:news_item></item>
<item><title>northern lights</title><ht:news_item><ht:news_item_title>Aurora seen far south</ht:news_item_title>
<ht:news_item_snippet>Solar storm lights up the sky</ht:news_item_snippet></ht:news_item></item>
</channel></rss>"""

REDDIT = b"""<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>t3_a</id><title>TIL that a war ended because of a dog</title></entry>
<entry><id>t3_b</id><title>TIL that honey never spoils</title></entry></feed>"""


class R:
    def __init__(self, content):
        self.status_code, self.content, self.text = 200, content, ""


def _fake(monkeypatch, content):
    class S:
        def get(self, *a, **k):
            return R(content)
    monkeypatch.setattr(T, "http", lambda: S())


def test_trends_skips_sensitive_and_used(monkeypatch, tmp_path):
    _fake(monkeypatch, TRENDS)
    h = History(tmp_path / "h.db")
    t = T.from_trends(Settings(), h)
    assert t.subject == "northern lights" and "Solar storm" in t.context
    h.mark_topic(t.key)
    assert T.from_trends(Settings(), h) is None


def test_reddit_rss(monkeypatch, tmp_path):
    _fake(monkeypatch, REDDIT)
    t = T.from_reddit(Settings(), History(tmp_path / "h.db"))
    assert t.subject == "honey never spoils" and t.key == "reddit:t3_b"


def test_sensitive_filter():
    assert T.SENSITIVE.search("Anura Kumara Dissanayake is elected as the 9th President")
    assert not T.SENSITIVE.search("The first transatlantic telegraph cable is completed")


def test_failed_source_falls_back_to_niche(monkeypatch, tmp_path):
    def boom(*a):
        raise RuntimeError("offline")
    monkeypatch.setattr(T, "from_trends", boom)
    t = T.pick_topic(Settings(niches=["space"]), History(tmp_path / "h.db"), source="trending")
    assert t.source == "niche" and t.subject == "space"
