"""Read-only view of the local FLOW sqlite store used by the guided scenarios."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class Obs:
    id: str
    ts: datetime
    app: str | None
    title: str | None
    summary: str | None
    category: str
    alignment: float | None
    confidence: float | None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def excluded(self) -> bool:
        return bool(self.meta.get("excluded"))

    @property
    def blocker(self) -> str | None:
        vision = self.meta.get("vision")
        blocker = vision.get("possible_blocker") if isinstance(vision, dict) else None
        return blocker if isinstance(blocker, str) and blocker else None


@dataclass(frozen=True, slots=True)
class Intervention:
    id: str
    ts: datetime
    reason: str
    channel: str
    status: str
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        """blocker | remind_goal | other, from reason + metadata only (never the spoken text)."""
        text = f"{self.reason} {json.dumps(self.meta, sort_keys=True)}".casefold()
        if "blocker" in text or "stuck" in text:
            return "blocker"
        if "remind_goal" in text or "drift" in text or "goal" in text:
            return "remind_goal"
        return "other"


class StoreView:
    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir)
        self.path = self.root / "flow.sqlite3"

    def exists(self) -> bool:
        return self.path.is_file()

    def _connect(self) -> sqlite3.Connection:
        try:
            db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)
            db.execute("SELECT 1 FROM flow_sessions LIMIT 1")
        except sqlite3.OperationalError:
            db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        db = self._connect()
        try:
            return db.execute(sql, params).fetchall()
        except sqlite3.DatabaseError:
            return []
        finally:
            db.close()

    def active_session(self, session_id: str | None = None) -> dict[str, Any] | None:
        if session_id:
            rows = self._rows("SELECT id, goal, status FROM flow_sessions WHERE id=?", (session_id,))
        else:
            rows = self._rows("SELECT id, goal, status FROM flow_sessions WHERE status='active' "
                              "ORDER BY started_at DESC LIMIT 1")
        return dict(rows[0]) if rows else None

    def observations(self, session_id: str, since: datetime) -> list[Obs]:
        rows = self._rows("SELECT * FROM flow_observations WHERE session_id=? ORDER BY timestamp DESC LIMIT 2000",
                          (session_id,))
        result = [Obs(r["id"], _ts(r["timestamp"]), r["app_name"], r["window_title"], r["activity_summary"],
                      r["category"], r["goal_alignment"], r["confidence"], _json(r["metadata_json"]))
                  for r in rows]
        return sorted((item for item in result if item.ts >= since), key=lambda item: item.ts)

    def interventions(self, session_id: str, since: datetime) -> list[Intervention]:
        rows = self._rows("SELECT * FROM flow_interventions WHERE session_id=? ORDER BY timestamp DESC LIMIT 500",
                          (session_id,))
        result = [Intervention(r["id"], _ts(r["timestamp"]), r["reason"], r["channel"], r["status"],
                               _json(r["metadata_json"])) for r in rows]
        return sorted((item for item in result if item.ts >= since), key=lambda item: item.ts)

    def database_files(self) -> list[Path]:
        return [p for p in (self.path, self.path.with_name(self.path.name + "-wal"),
                            self.path.with_name(self.path.name + "-shm")) if p.is_file()]

    def contains_text(self, needle: str) -> bool:
        """True if ``needle`` occurs anywhere in the db or its WAL/SHM files (chunked byte scan)."""
        raw = needle.encode("utf-8")
        for path in self.database_files():
            tail = b""
            with open(path, "rb") as handle:
                while chunk := handle.read(1 << 20):
                    if raw in tail + chunk:
                        return True
                    tail = chunk[-(len(raw) - 1):] if len(raw) > 1 else b""
        return False

    def image_files_since(self, since: datetime) -> list[Path]:
        suffixes = {".png", ".jpg", ".jpeg", ".heic", ".tiff", ".webp", ".gif"}
        found = []
        since = since - timedelta(seconds=1)  # filesystem mtimes are coarser than our clock
        for path in self.root.rglob("*"):
            try:
                if path.is_file() and path.suffix.casefold() in suffixes and \
                        datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) >= since:
                    found.append(path)
            except OSError:
                continue
        return found


def _json(text: str | None) -> dict[str, Any]:
    try:
        value = json.loads(text or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}
