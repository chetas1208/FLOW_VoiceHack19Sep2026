"""Local durable state owned by the remote layer: executed-command ledger, entity mirror, host settings.

Lives in the same SQLite file as the rest of FLOW (its own tables, created idempotently), so a daemon
restart keeps the exactly-once guarantee for commands and can rebuild tasks/approvals/recommendations.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_executed_commands (
  command_id TEXT PRIMARY KEY, type TEXT NOT NULL, user_id TEXT NOT NULL, session_id TEXT,
  source TEXT NOT NULL, status TEXT NOT NULL, result_json TEXT, started_at TEXT NOT NULL,
  finished_at TEXT, boot_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_flow_executed_commands_finished ON flow_executed_commands(finished_at);
CREATE TABLE IF NOT EXISTS flow_entities (
  session_id TEXT NOT NULL, kind TEXT NOT NULL, entity_id TEXT NOT NULL, revision INTEGER NOT NULL,
  status TEXT, data_json TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (session_id, kind, entity_id));
CREATE TABLE IF NOT EXISTS flow_host_settings (
  session_id TEXT NOT NULL, key TEXT NOT NULL, value_json TEXT NOT NULL, PRIMARY KEY (session_id, key));
"""

BOOT_ID = secrets.token_hex(6)  # identifies this daemon process; a 'running' row from another boot is stale


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocalLedger:
    def __init__(self, store) -> None:
        self.store = store
        with self._tx() as db:
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        db = self.store.connection()
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
        db = self.store.connection()
        try:
            yield db
        finally:
            db.close()

    # ---- executed commands -----------------------------------------------------------------------
    def begin_command(self, command_id: str, type_: str, user_id: str, session_id: str | None,
                      source: str) -> tuple[str, dict[str, Any] | None]:
        """Claim ``command_id``. Returns ("new", None) for the first caller; otherwise ("done"|"running", row)."""
        with self._tx() as db:
            cursor = db.execute(
                """INSERT INTO flow_executed_commands(command_id,type,user_id,session_id,source,status,started_at,boot_id)
                   VALUES (?,?,?,?,?, 'running', ?, ?) ON CONFLICT(command_id) DO NOTHING""",
                (command_id, type_, user_id, session_id, source, _now(), BOOT_ID))
            if cursor.rowcount == 1:
                return "new", None
            row = db.execute("SELECT * FROM flow_executed_commands WHERE command_id=?", (command_id,)).fetchone()
            record = self._command(row)
            if record["status"] == "running" and record["boot_id"] != BOOT_ID:
                # The process that started it died mid-execution. Re-running could double effects, so report failure.
                record["status"] = "failed"
                record["result"] = {"error": "the FLOW daemon restarted while this command was running; send it again"}
                db.execute("UPDATE flow_executed_commands SET status='failed', result_json=?, finished_at=? WHERE command_id=?",
                           (json.dumps(record["result"]), _now(), command_id))
            return ("running" if record["status"] == "running" else "done"), record

    def finish_command(self, command_id: str, status: str, result: dict[str, Any] | None) -> None:
        with self._tx() as db:
            db.execute("UPDATE flow_executed_commands SET status=?, result_json=?, finished_at=? WHERE command_id=?",
                       (status, json.dumps(result if result is not None else {}, default=str), _now(), command_id))

    def get_command(self, command_id: str) -> dict[str, Any] | None:
        with self._read() as db:
            row = db.execute("SELECT * FROM flow_executed_commands WHERE command_id=?", (command_id,)).fetchone()
        return self._command(row) if row else None

    def count_commands(self) -> int:
        with self._read() as db:
            return int(db.execute("SELECT COUNT(*) FROM flow_executed_commands").fetchone()[0])

    def prune_commands(self, older_than_days: int = 30) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        with self._tx() as db:
            return db.execute("DELETE FROM flow_executed_commands WHERE finished_at IS NOT NULL AND finished_at < ?",
                              (cutoff,)).rowcount

    @staticmethod
    def _command(row: sqlite3.Row) -> dict[str, Any]:
        return {"command_id": row["command_id"], "type": row["type"], "user_id": row["user_id"],
                "session_id": row["session_id"], "source": row["source"], "status": row["status"],
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "started_at": row["started_at"], "finished_at": row["finished_at"], "boot_id": row["boot_id"]}

    # ---- entity mirror ---------------------------------------------------------------------------
    def put_entity(self, session_id: str, kind: str, entity_id: str, revision: int, data: dict[str, Any],
                   status: str | None = None) -> bool:
        """Upsert when ``revision`` is not older than what is stored. Returns True when the row changed."""
        with self._tx() as db:
            row = db.execute("SELECT revision, data_json FROM flow_entities WHERE session_id=? AND kind=? AND entity_id=?",
                             (session_id, kind, entity_id)).fetchone()
            body = json.dumps(data, sort_keys=True, default=str)
            if row is not None and (row["revision"] > revision or (row["revision"] == revision and row["data_json"] == body)):
                return False
            db.execute("""INSERT INTO flow_entities(session_id,kind,entity_id,revision,status,data_json,updated_at)
                          VALUES (?,?,?,?,?,?,?) ON CONFLICT(session_id,kind,entity_id) DO UPDATE SET
                          revision=excluded.revision, status=excluded.status, data_json=excluded.data_json,
                          updated_at=excluded.updated_at""",
                       (session_id, kind, entity_id, revision, status, body, _now()))
            return True

    def get_entity(self, session_id: str, kind: str, entity_id: str) -> dict[str, Any] | None:
        with self._read() as db:
            row = db.execute("SELECT * FROM flow_entities WHERE session_id=? AND kind=? AND entity_id=?",
                             (session_id, kind, entity_id)).fetchone()
        return self._entity(row) if row else None

    def find_entity(self, kind: str, entity_id: str) -> dict[str, Any] | None:
        with self._read() as db:
            row = db.execute("SELECT * FROM flow_entities WHERE kind=? AND entity_id=? ORDER BY updated_at DESC LIMIT 1",
                             (kind, entity_id)).fetchone()
        return self._entity(row) if row else None

    def list_entities(self, kind: str, session_id: str | None = None, status: str | None = None,
                      limit: int = 200) -> list[dict[str, Any]]:
        query, params = "SELECT * FROM flow_entities WHERE kind=?", [kind]
        if session_id:
            query += " AND session_id=?"
            params.append(session_id)
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY updated_at DESC, entity_id LIMIT ?"
        params.append(limit)
        with self._read() as db:
            rows = db.execute(query, params).fetchall()
        return [self._entity(row) for row in rows]

    @staticmethod
    def _entity(row: sqlite3.Row) -> dict[str, Any]:
        return {"session_id": row["session_id"], "kind": row["kind"], "id": row["entity_id"], "revision": row["revision"],
                "status": row["status"], "data": json.loads(row["data_json"]), "updated_at": row["updated_at"]}

    # ---- per-session host settings (local only, never uploaded) ----------------------------------------
    def set_setting(self, session_id: str, key: str, value: Any) -> None:
        with self._tx() as db:
            db.execute("""INSERT INTO flow_host_settings(session_id,key,value_json) VALUES (?,?,?)
                          ON CONFLICT(session_id,key) DO UPDATE SET value_json=excluded.value_json""",
                       (session_id, key, json.dumps(value, default=str)))

    def get_setting(self, session_id: str, key: str, default: Any = None) -> Any:
        with self._read() as db:
            row = db.execute("SELECT value_json FROM flow_host_settings WHERE session_id=? AND key=?",
                             (session_id, key)).fetchone()
        return json.loads(row[0]) if row else default

    def settings(self, session_id: str) -> dict[str, Any]:
        with self._read() as db:
            rows = db.execute("SELECT key, value_json FROM flow_host_settings WHERE session_id=?", (session_id,)).fetchall()
        return {row[0]: json.loads(row[1]) for row in rows}
