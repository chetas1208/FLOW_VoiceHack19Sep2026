"""Thread-safe SQLite persistence for the FLOW domain."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .events import FlowEvent
from .models import (ActivityCategory, Intervention, InterventionChannel, InterventionStatus,
                     Observation, SessionStatus, WorkSession, ensure_utc)


class FlowStore:
    def __init__(self, directory: str | Path) -> None:
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "flow.sqlite3"
        with self.connection() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS flow_sessions (
              id TEXT PRIMARY KEY, goal TEXT NOT NULL, status TEXT NOT NULL,
              started_at TEXT NOT NULL, updated_at TEXT NOT NULL, ended_at TEXT,
              created_by TEXT, metadata_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS flow_observations (
              id TEXT PRIMARY KEY, session_id TEXT NOT NULL, timestamp TEXT NOT NULL,
              source TEXT NOT NULL, app_name TEXT, window_title TEXT, activity_summary TEXT,
              category TEXT NOT NULL, goal_alignment REAL, progress_signal REAL,
              confidence REAL, metadata_json TEXT NOT NULL,
              FOREIGN KEY(session_id) REFERENCES flow_sessions(id));
            CREATE TABLE IF NOT EXISTS flow_interventions (
              id TEXT PRIMARY KEY, session_id TEXT NOT NULL, timestamp TEXT NOT NULL,
              reason TEXT NOT NULL, channel TEXT NOT NULL, message TEXT, status TEXT NOT NULL,
              metadata_json TEXT NOT NULL, FOREIGN KEY(session_id) REFERENCES flow_sessions(id));
            CREATE TABLE IF NOT EXISTS flow_events (
              event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, type TEXT NOT NULL,
              timestamp TEXT NOT NULL, sequence INTEGER NOT NULL, data_json TEXT NOT NULL,
              UNIQUE(session_id, sequence), FOREIGN KEY(session_id) REFERENCES flow_sessions(id));
            CREATE INDEX IF NOT EXISTS idx_flow_sessions_status ON flow_sessions(status, started_at);
            CREATE INDEX IF NOT EXISTS idx_flow_observations_session_time ON flow_observations(session_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_flow_interventions_session_time ON flow_interventions(session_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_flow_events_session_sequence ON flow_events(session_id, sequence);
            """)

    def connection(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def save_session(self, session: WorkSession) -> None:
        with self.connection() as db:
            db.execute("""INSERT INTO flow_sessions
              (id,goal,status,started_at,updated_at,ended_at,created_by,metadata_json)
              VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
              goal=excluded.goal, status=excluded.status, started_at=excluded.started_at,
              updated_at=excluded.updated_at, ended_at=excluded.ended_at,
              created_by=excluded.created_by, metadata_json=excluded.metadata_json""", (session.id, session.goal, session.status.value,
              session.started_at.isoformat(), session.updated_at.isoformat(),
              session.ended_at.isoformat() if session.ended_at else None, session.created_by,
              self._json(session.metadata)))

    def get_session(self, session_id: str) -> WorkSession | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM flow_sessions WHERE id=?", (session_id,)).fetchone()
        return self._session(row) if row else None

    def list_sessions(self, status: SessionStatus | None = None, limit: int = 50) -> list[WorkSession]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be 1..100")
        query = "SELECT * FROM flow_sessions" + (" WHERE status=?" if status else "") + " ORDER BY started_at DESC LIMIT ?"
        params: tuple[Any, ...] = ((status.value, limit) if status else (limit,))
        with self.connection() as db:
            rows = db.execute(query, params).fetchall()
        return [self._session(row) for row in rows]

    @staticmethod
    def _session(row: sqlite3.Row) -> WorkSession:
        return WorkSession(row["id"], row["goal"], SessionStatus(row["status"]),
                           datetime.fromisoformat(row["started_at"]), datetime.fromisoformat(row["updated_at"]),
                           datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
                           row["created_by"], json.loads(row["metadata_json"]))

    def save_observation(self, observation: Observation) -> None:
        with self.connection() as db:
            db.execute("""INSERT INTO flow_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                observation.id, observation.session_id, observation.timestamp.isoformat(), observation.source,
                observation.app_name, observation.window_title, observation.activity_summary,
                observation.category.value, observation.goal_alignment, observation.progress_signal,
                observation.confidence, self._json(observation.metadata)))

    def list_observations(self, session_id: str) -> list[Observation]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM flow_observations WHERE session_id=? ORDER BY timestamp,id", (session_id,)).fetchall()
        return [Observation(row["id"], row["session_id"], datetime.fromisoformat(row["timestamp"]), row["source"],
                            row["app_name"], row["window_title"], row["activity_summary"], ActivityCategory(row["category"]),
                            row["goal_alignment"], row["progress_signal"], row["confidence"], json.loads(row["metadata_json"])) for row in rows]

    def save_intervention(self, intervention: Intervention) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO flow_interventions VALUES (?,?,?,?,?,?,?,?)", (
                intervention.id, intervention.session_id, intervention.timestamp.isoformat(), intervention.reason,
                intervention.channel.value, intervention.message, intervention.status.value, self._json(intervention.metadata)))

    def list_interventions(self, session_id: str) -> list[Intervention]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM flow_interventions WHERE session_id=? ORDER BY timestamp,id", (session_id,)).fetchall()
        return [Intervention(row["id"], row["session_id"], datetime.fromisoformat(row["timestamp"]), row["reason"],
                             InterventionChannel(row["channel"]), row["message"], InterventionStatus(row["status"]),
                             json.loads(row["metadata_json"])) for row in rows]

    def save_event(self, item: FlowEvent) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO flow_events VALUES (?,?,?,?,?,?)", (item.event_id, item.session_id, item.type,
                       item.timestamp.isoformat(), item.sequence, self._json(item.data)))

    def list_events(self, session_id: str, after: int = 0, limit: int = 500) -> list[FlowEvent]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM flow_events WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                              (session_id, after, limit)).fetchall()
        return [FlowEvent(row["event_id"], row["type"], row["session_id"], datetime.fromisoformat(row["timestamp"]),
                          row["sequence"], json.loads(row["data_json"])) for row in rows]

    def next_sequence(self, session_id: str) -> int:
        with self.connection() as db:
            row = db.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM flow_events WHERE session_id=?", (session_id,)).fetchone()
        return int(row[0])
