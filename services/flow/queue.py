"""Bounded offline semantic-event queue. Raw frames are never queued."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class OfflineQueue:
    def __init__(self, path: str | Path, max_items: int = 10000) -> None:
        self.path, self.max_items = Path(path), max_items
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS queue (id INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)")

    def put(self, payload: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as db:
            count = db.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
            if count >= self.max_items:
                db.execute("DELETE FROM queue WHERE id=(SELECT MIN(id) FROM queue)")
            db.execute("INSERT INTO queue(payload) VALUES (?)", (json.dumps(payload, sort_keys=True),))

    def pop_batch(self, limit: int = 100) -> list[dict[str, Any]]:
        items = self.peek_batch(limit)
        self.ack([item[0] for item in items])
        return [item[1] for item in items]

    def peek_batch(self, limit: int = 100) -> list[tuple[int, dict[str, Any]]]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT id,payload FROM queue ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [(int(row[0]), json.loads(row[1])) for row in rows]

    def ack(self, ids: list[int]) -> None:
        if not ids:
            return
        with sqlite3.connect(self.path) as db:
            db.executemany("DELETE FROM queue WHERE id=?", [(item,) for item in ids])

    def __len__(self) -> int:
        with sqlite3.connect(self.path) as db:
            return int(db.execute("SELECT COUNT(*) FROM queue").fetchone()[0])
