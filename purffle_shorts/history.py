"""SQLite history: every video made, what was uploaded or scheduled, which stock clips and topics
were used (so nothing repeats), today's upload count (YouTube quota), the idea queue filled by the
planner, and view counts for the videos that are live."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    subject TEXT, source TEXT, topic TEXT, style TEXT, language TEXT,
    title TEXT, description TEXT, tags TEXT,
    folder TEXT, video_path TEXT, duration REAL,
    llm TEXT, voice TEXT,
    status TEXT NOT NULL,          -- rendered | queued | uploaded | scheduled | failed
    youtube_id TEXT, publish_at TEXT, uploaded_at TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS media_used (key TEXT PRIMARY KEY, used_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS topics_used (key TEXT PRIMARY KEY, used_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    subject TEXT NOT NULL,
    style TEXT, notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | used
    used_at TEXT, video_id INTEGER
);
"""

# Columns added after 2.0; existing databases get them on open.
VIDEO_COLUMNS = {
    "score": "INTEGER",            # Script Doctor retention score, 0-100
    "parent_id": "INTEGER",        # the original video when this one is a translated copy
    "views": "INTEGER", "likes": "INTEGER", "comments": "INTEGER", "stats_at": "TEXT",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class History:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._db() as c:
            c.executescript(SCHEMA)
            have = {r["name"] for r in c.execute("PRAGMA table_info(videos)")}
            for col, kind in VIDEO_COLUMNS.items():
                if col not in have:
                    c.execute(f"ALTER TABLE videos ADD COLUMN {col} {kind}")

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                conn.close()

    def _exec(self, sql: str, args: tuple = ()) -> int:
        with self._db() as c:
            return c.execute(sql, args).lastrowid or 0

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._db() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    # -- videos --
    def add_video(self, **fields) -> int:
        fields.setdefault("created_at", now_iso())
        if isinstance(fields.get("tags"), list):
            fields["tags"] = json.dumps(fields["tags"])
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        return self._exec(f"INSERT INTO videos ({cols}) VALUES ({marks})", tuple(fields.values()))

    def update_video(self, vid: int, **fields) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE videos SET {sets} WHERE id = ?", (*fields.values(), vid))

    def get(self, vid: int) -> dict | None:
        rows = self._all("SELECT * FROM videos WHERE id = ?", (vid,))
        return rows[0] if rows else None

    def recent(self, limit: int = 20) -> list[dict]:
        return self._all("SELECT * FROM videos ORDER BY id DESC LIMIT ?", (limit,))

    def delete_video(self, vid: int) -> None:
        self._exec("DELETE FROM videos WHERE id = ?", (vid,))

    def recent_titles(self, limit: int = 40) -> list[str]:
        return [r["title"] for r in self._all(
            "SELECT title FROM videos WHERE title IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,))]

    def pending_uploads(self, statuses: tuple[str, ...] = ("queued",)) -> list[dict]:
        """queued = deferred by the daily quota; rendered = made with --no-upload."""
        marks = ", ".join("?" for _ in statuses)
        return self._all(f"SELECT * FROM videos WHERE status IN ({marks}) AND video_path IS NOT NULL ORDER BY id",
                         statuses)

    def uploads_since(self, since_iso: str) -> int:
        return self._all("SELECT COUNT(*) AS n FROM videos WHERE uploaded_at >= ?", (since_iso,))[0]["n"]

    def scheduled_times(self) -> list[str]:
        return [r["publish_at"] for r in self._all(
            "SELECT publish_at FROM videos WHERE publish_at IS NOT NULL AND status = 'scheduled'")]

    def stats(self) -> dict:
        rows = self._all("SELECT status, COUNT(*) AS n FROM videos GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    # -- channel performance --
    def live_video_ids(self, limit: int = 500) -> list[str]:
        return [r["youtube_id"] for r in self._all(
            "SELECT youtube_id FROM videos WHERE youtube_id IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,))]

    def set_stats(self, youtube_id: str, views: int, likes: int, comments: int) -> None:
        self._exec("UPDATE videos SET views = ?, likes = ?, comments = ?, stats_at = ? WHERE youtube_id = ?",
                   (views, likes, comments, now_iso(), youtube_id))

    def performers(self, n: int = 5, *, best: bool = True, min_age_hours: int = 48) -> list[dict]:
        """Most (or least) viewed videos that have been public long enough for the numbers to mean something."""
        cutoff = datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() - min_age_hours * 3600,
                                        timezone.utc).isoformat(timespec="seconds")
        order = "DESC" if best else "ASC"
        return self._all(
            "SELECT id, title, style, views, likes, comments FROM videos WHERE views IS NOT NULL "
            f"AND COALESCE(publish_at, uploaded_at) <= ? ORDER BY views {order} LIMIT ?", (cutoff, n))

    # -- idea queue (planner) --
    def add_idea(self, subject: str, style: str = "", notes: str = "") -> int:
        return self._exec("INSERT INTO ideas (created_at, subject, style, notes) VALUES (?, ?, ?, ?)",
                          (now_iso(), subject.strip(), style or None, notes or None))

    def ideas(self, status: str | None = "pending", limit: int = 200) -> list[dict]:
        if status:
            return self._all("SELECT * FROM ideas WHERE status = ? ORDER BY id LIMIT ?", (status, limit))
        return self._all("SELECT * FROM ideas ORDER BY id DESC LIMIT ?", (limit,))

    def claim_idea(self) -> dict | None:
        """Take the oldest pending idea (atomically, so parallel workers never get the same one)."""
        with self._db() as c:
            row = c.execute("SELECT * FROM ideas WHERE status = 'pending' ORDER BY id LIMIT 1").fetchone()
            if not row:
                return None
            c.execute("UPDATE ideas SET status = 'used', used_at = ? WHERE id = ?", (now_iso(), row["id"]))
            return dict(row)

    def link_idea(self, idea_id: int, video_id: int) -> None:
        self._exec("UPDATE ideas SET video_id = ? WHERE id = ?", (video_id, idea_id))

    def release_idea(self, idea_id: int) -> None:
        """Put an idea back in the queue after its video failed."""
        self._exec("UPDATE ideas SET status = 'pending', used_at = NULL WHERE id = ?", (idea_id,))

    def delete_idea(self, idea_id: int) -> None:
        self._exec("DELETE FROM ideas WHERE id = ?", (idea_id,))

    # -- de-duplication --
    def used_media(self) -> set[str]:
        return {r["key"] for r in self._all("SELECT key FROM media_used")}

    def mark_media(self, keys: list[str]) -> None:
        ts = now_iso()
        with self._db() as c:
            c.executemany("INSERT OR IGNORE INTO media_used (key, used_at) VALUES (?, ?)", [(k, ts) for k in keys])

    def topic_used(self, key: str) -> bool:
        return bool(self._all("SELECT 1 FROM topics_used WHERE key = ?", (key.lower(),)))

    def mark_topic(self, key: str) -> None:
        self._exec("INSERT OR IGNORE INTO topics_used (key, used_at) VALUES (?, ?)", (key.lower(), now_iso()))
