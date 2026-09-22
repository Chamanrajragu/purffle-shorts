"""SQLite history: every video made, what was uploaded or scheduled, which stock clips and topics
were used (so nothing repeats), and today's upload count (YouTube quota)."""

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
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class History:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._db() as c:
            c.executescript(SCHEMA)

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
