"""Thread- and process-safe SQLite persistence for the FLOW domain.

Every write runs inside ``BEGIN IMMEDIATE`` so per-session ``sequence`` numbers (observations and events) are
assigned under the database write lock: two processes (CLI + daemon) can never mint the same sequence. Additive
schema changes are versioned with ``PRAGMA user_version`` and applied under the same lock.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .events import FlowEvent
from .models import (ActivityCategory, Intervention, InterventionChannel, InterventionStatus,
                     Observation, SessionStatus, WorkSession, ensure_utc)

SCHEMA_VERSION = 2

_BASE_SCHEMA = """
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
"""

_V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
  session_id TEXT NOT NULL, kind TEXT NOT NULL, entity_id TEXT NOT NULL, revision INTEGER NOT NULL,
  status TEXT, data_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (session_id, kind, entity_id));
CREATE INDEX IF NOT EXISTS idx_entities_session_kind_status ON entities(session_id, kind, status);
CREATE INDEX IF NOT EXISTS idx_entities_kind_status ON entities(kind, status);
CREATE TABLE IF NOT EXISTS paired_clients (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, public_key TEXT NOT NULL, created_at TEXT NOT NULL,
  last_seen_at TEXT, revoked_at TEXT, permissions TEXT NOT NULL DEFAULT '[]');
CREATE INDEX IF NOT EXISTS idx_paired_clients_public_key ON paired_clients(public_key);
CREATE TABLE IF NOT EXISTS pairing_tokens (
  token_hash TEXT PRIMARY KEY, mode TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS commands_seen (
  command_id TEXT PRIMARY KEY, client_id TEXT, session_id TEXT, type TEXT NOT NULL, status TEXT NOT NULL,
  payload_json TEXT, result_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT);
CREATE INDEX IF NOT EXISTS idx_commands_seen_session ON commands_seen(session_id, created_at);
"""

ENTITY_KINDS = ("task", "approval", "recommendation", "subtask", "goal_version", "chat", "runtime_state")
DEFAULT_CLIENT_PERMISSIONS = ("read", "command")
MAX_PAIRING_ATTEMPTS = 5


def _ts(value: datetime | None = None) -> str:
    """Fixed-width UTC timestamp so lexical order == chronological order in SQL comparisons."""
    value = ensure_utc(value or datetime.now(timezone.utc))
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class FlowStore:
    def __init__(self, directory: str | Path) -> None:
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "flow.sqlite3"
        db = self.connection()
        try:
            db.execute("PRAGMA journal_mode=WAL")
        finally:
            db.close()
        self._migrate()

    # ---- connections ---------------------------------------------------------------------------
    def connection(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """Write transaction holding the database write lock from the start (``BEGIN IMMEDIATE``)."""
        db = self.connection()
        try:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")
        finally:
            db.close()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        db = self.connection()
        try:
            yield db
        finally:
            db.close()

    # ---- migrations ----------------------------------------------------------------------------
    def _migrate(self) -> None:
        db = self.connection()
        try:
            if db.execute("PRAGMA user_version").fetchone()[0] >= SCHEMA_VERSION:
                return
            db.execute("BEGIN IMMEDIATE")
            try:
                version = db.execute("PRAGMA user_version").fetchone()[0]  # re-check under the lock
                if version < 1:
                    for statement in _BASE_SCHEMA.split(";"):
                        if statement.strip():
                            db.execute(statement)
                if version < 2:
                    columns = {row[1] for row in db.execute("PRAGMA table_info(flow_observations)")}
                    if "sequence" not in columns:
                        db.execute("ALTER TABLE flow_observations ADD COLUMN sequence INTEGER")
                    db.execute("""UPDATE flow_observations SET sequence = (
                        SELECT COUNT(*) FROM flow_observations o2 WHERE o2.session_id = flow_observations.session_id
                          AND (o2.timestamp < flow_observations.timestamp
                               OR (o2.timestamp = flow_observations.timestamp AND o2.id <= flow_observations.id)))
                        WHERE sequence IS NULL""")
                    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_flow_observations_session_sequence "
                               "ON flow_observations(session_id, sequence)")
                    for statement in _V2_SCHEMA.split(";"):
                        if statement.strip():
                            db.execute(statement)
                if version < SCHEMA_VERSION:
                    db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        finally:
            db.close()

    def schema_version(self) -> int:
        with self._read() as db:
            return int(db.execute("PRAGMA user_version").fetchone()[0])

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    # ---- sessions ------------------------------------------------------------------------------
    def save_session(self, session: WorkSession, sync: bool = False) -> None:
        with self._tx() as db:
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
        with self._read() as db:
            row = db.execute("SELECT * FROM flow_sessions WHERE id=?", (session_id,)).fetchone()
        return self._session(row) if row else None

    def list_sessions(self, status: SessionStatus | None = None, limit: int = 50) -> list[WorkSession]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be 1..100")
        query = "SELECT * FROM flow_sessions" + (" WHERE status=?" if status else "") + " ORDER BY started_at DESC LIMIT ?"
        params: tuple[Any, ...] = ((status.value, limit) if status else (limit,))
        with self._read() as db:
            rows = db.execute(query, params).fetchall()
        return [self._session(row) for row in rows]

    @staticmethod
    def _session(row: sqlite3.Row) -> WorkSession:
        return WorkSession(row["id"], row["goal"], SessionStatus(row["status"]),
                           datetime.fromisoformat(row["started_at"]), datetime.fromisoformat(row["updated_at"]),
                           datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
                           row["created_by"], json.loads(row["metadata_json"]))

    # ---- observations --------------------------------------------------------------------------
    def save_observation(self, observation: Observation, sync: bool = False) -> Observation:
        """Insert, assigning the next per-session ``sequence`` inside the write transaction."""
        with self._tx() as db:
            sequence = int(db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM flow_observations WHERE session_id=?",
                                      (observation.session_id,)).fetchone()[0])
            observation.sequence = sequence
            db.execute("""INSERT INTO flow_observations
                (id,session_id,timestamp,source,app_name,window_title,activity_summary,category,goal_alignment,
                 progress_signal,confidence,metadata_json,sequence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                observation.id, observation.session_id, observation.timestamp.isoformat(), observation.source,
                observation.app_name, observation.window_title, observation.activity_summary,
                observation.category.value, observation.goal_alignment, observation.progress_signal,
                observation.confidence, self._json(observation.metadata), sequence))
        return observation

    @staticmethod
    def _observation(row: sqlite3.Row) -> Observation:
        return Observation(row["id"], row["session_id"], datetime.fromisoformat(row["timestamp"]), row["source"],
                           row["app_name"], row["window_title"], row["activity_summary"], ActivityCategory(row["category"]),
                           row["goal_alignment"], row["progress_signal"], row["confidence"],
                           json.loads(row["metadata_json"]), row["sequence"])

    def list_observations(self, session_id: str) -> list[Observation]:
        with self._read() as db:
            rows = db.execute("SELECT * FROM flow_observations WHERE session_id=? ORDER BY timestamp,id", (session_id,)).fetchall()
        return [self._observation(row) for row in rows]

    def list_observations_after(self, session_id: str, after_sequence: int = 0, limit: int = 500) -> list[Observation]:
        with self._read() as db:
            rows = db.execute("SELECT * FROM flow_observations WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                              (session_id, after_sequence, limit)).fetchall()
        return [self._observation(row) for row in rows]

    def observation_count(self, session_id: str) -> int:
        with self._read() as db:
            return int(db.execute("SELECT COUNT(*) FROM flow_observations WHERE session_id=?", (session_id,)).fetchone()[0])

    # ---- interventions -------------------------------------------------------------------------
    def save_intervention(self, intervention: Intervention, sync: bool = False) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO flow_interventions VALUES (?,?,?,?,?,?,?,?)", (
                intervention.id, intervention.session_id, intervention.timestamp.isoformat(), intervention.reason,
                intervention.channel.value, intervention.message, intervention.status.value, self._json(intervention.metadata)))
    def list_interventions(self, session_id: str) -> list[Intervention]:
        with self._read() as db:
            rows = db.execute("SELECT * FROM flow_interventions WHERE session_id=? ORDER BY timestamp,id", (session_id,)).fetchall()
        return [Intervention(row["id"], row["session_id"], datetime.fromisoformat(row["timestamp"]), row["reason"],
                             InterventionChannel(row["channel"]), row["message"], InterventionStatus(row["status"]),
                             json.loads(row["metadata_json"])) for row in rows]

    def has_intervention_reason(self, session_id: str, reason: str) -> bool:
        with self._read() as db:
            return db.execute("SELECT 1 FROM flow_interventions WHERE session_id=? AND reason=? LIMIT 1",
                              (session_id, reason)).fetchone() is not None

    # ---- events --------------------------------------------------------------------------------
    def append_event(self, session_id: str, event_type: str, data: dict[str, Any], event_id: str,
                     sync: bool = False, timestamp: datetime | None = None) -> FlowEvent:
        """Create an event with the next per-session sequence, assigned inside the write transaction."""
        stamp = ensure_utc(timestamp or datetime.now(timezone.utc))
        with self._tx() as db:
            sequence = int(db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM flow_events WHERE session_id=?",
                                      (session_id,)).fetchone()[0])
            item = FlowEvent(event_id, event_type, session_id, stamp, sequence, data)
            db.execute("INSERT INTO flow_events VALUES (?,?,?,?,?,?)", (item.event_id, item.session_id, item.type,
                       item.timestamp.isoformat(), item.sequence, self._json(item.data)))
        return item

    def save_event(self, item: FlowEvent, sync: bool = False) -> None:
        """Persist an event whose sequence the caller already chose (prefer ``append_event``)."""
        with self._tx() as db:
            db.execute("INSERT INTO flow_events VALUES (?,?,?,?,?,?)", (item.event_id, item.session_id, item.type,
                       item.timestamp.isoformat(), item.sequence, self._json(item.data)))
    @staticmethod
    def _event(row: sqlite3.Row) -> FlowEvent:
        return FlowEvent(row["event_id"], row["type"], row["session_id"], datetime.fromisoformat(row["timestamp"]),
                         row["sequence"], json.loads(row["data_json"]))

    def list_events(self, session_id: str, after: int = 0, limit: int = 500) -> list[FlowEvent]:
        with self._read() as db:
            rows = db.execute("SELECT * FROM flow_events WHERE session_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                              (session_id, after, limit)).fetchall()
        return [self._event(row) for row in rows]

    def latest_event(self, session_id: str, event_type: str) -> FlowEvent | None:
        with self._read() as db:
            row = db.execute("SELECT * FROM flow_events WHERE session_id=? AND type=? ORDER BY sequence DESC LIMIT 1",
                             (session_id, event_type)).fetchone()
        return self._event(row) if row else None

    def next_sequence(self, session_id: str) -> int:
        with self._read() as db:
            row = db.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM flow_events WHERE session_id=?", (session_id,)).fetchone()
        return int(row[0])

    # Compatibility no-ops: cloud synchronization is optional and its durable
    # outbox is owned by the remote package when that package is installed.
    def enqueue(self, entity_type: str, entity_id: str, session_id: str, payload: dict[str, Any],
                sequence: int | None = None) -> bool:
        return False

    def enqueue_many(self, session_id: str, items: list[tuple[str, str, dict[str, Any], int | None]]) -> int:
        return 0
