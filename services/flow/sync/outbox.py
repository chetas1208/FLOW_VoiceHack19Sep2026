"""Durable transactional outbox.

A ``sync_outbox`` row is written in the **same SQLite transaction** as the entity it describes, so a crash can
never leave an entity without its upload record. ``SyncOutbox.reconcile`` repairs any that were nevertheless
missed (rows written by an older build, sync enabled after the fact, manual DB edits).

Ordering model: per session, the ``session`` row is uploaded first and ``summary`` then ``stop`` last; between
them observations, events, interventions, segments and entities are claimed in per-kind order (observations and
events by their sequence) in batches of up to 100.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

STATES = ("pending", "in_flight", "synced", "failed")
_RANK_SQL = "CASE entity_type WHEN 'session' THEN 0 WHEN 'summary' THEN 2 WHEN 'stop' THEN 3 ELSE 1 END"
_RANK = {"session": 0, "summary": 2, "stop": 3}
# Rows for these kinds are upserted (a newer revision replaces the queued payload); the rest are immutable.
REVISIONED = {"segment", "entity", "summary", "stop"}


def ts(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


@dataclass(slots=True)
class OutboxRow:
    id: int
    entity_type: str
    entity_id: str
    session_id: str
    sequence: int | None
    payload: dict[str, Any]
    state: str
    attempt_count: int
    next_attempt_at: str | None
    created_at: str
    synced_at: str | None
    last_error: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "OutboxRow":
        return cls(row["id"], row["entity_type"], row["entity_id"], row["session_id"], row["sequence"],
                   json.loads(row["payload"]), row["state"], row["attempt_count"], row["next_attempt_at"],
                   row["created_at"], row["synced_at"], row["last_error"])


@dataclass(slots=True)
class Claim:
    """A group of consecutive rows of one kind for one session, already marked ``in_flight``."""
    session_id: str
    entity_type: str
    rows: list[OutboxRow]


def enqueue(db: sqlite3.Connection, entity_type: str, entity_id: str, session_id: str, payload: dict[str, Any],
            sequence: int | None = None, now: datetime | None = None) -> bool:
    """Insert (or, for revisioned kinds, refresh) an outbox row on an open transaction. Returns True if it changed."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    now_s = ts(now)
    if entity_type in REVISIONED:
        cursor = db.execute(
            """INSERT INTO sync_outbox(entity_type,entity_id,session_id,sequence,payload,state,attempt_count,created_at)
               VALUES (?,?,?,?,?,'pending',0,?)
               ON CONFLICT(entity_type,entity_id) DO UPDATE SET payload=excluded.payload, state='pending',
                 attempt_count=0, next_attempt_at=NULL, last_error=NULL, synced_at=NULL
               WHERE sync_outbox.payload <> excluded.payload""",
            (entity_type, entity_id, session_id, sequence, body, now_s))
    else:
        cursor = db.execute(
            """INSERT INTO sync_outbox(entity_type,entity_id,session_id,sequence,payload,state,attempt_count,created_at)
               VALUES (?,?,?,?,?,'pending',0,?) ON CONFLICT(entity_type,entity_id) DO NOTHING""",
            (entity_type, entity_id, session_id, sequence, body, now_s))
    changed = cursor.rowcount > 0
    if changed and hasattr(db, "enqueued"):
        db.enqueued = True  # type: ignore[attr-defined]
    return changed


class SyncOutbox:
    def __init__(self, store) -> None:
        self.store = store

    # ---- claiming ------------------------------------------------------------------------------
    def claim_batches(self, now: datetime | None = None, max_batch: int = 100, max_sessions: int = 50) -> list[Claim]:
        now_s = ts(now)
        claims: list[Claim] = []
        with self.store._tx() as db:
            sessions = [r[0] for r in db.execute(
                "SELECT session_id FROM sync_outbox WHERE state='pending' GROUP BY session_id ORDER BY MIN(id) LIMIT ?",
                (max_sessions,))]
            for session_id in sessions:
                if db.execute("SELECT 1 FROM sync_outbox WHERE session_id=? AND state='in_flight' LIMIT 1",
                              (session_id,)).fetchone():
                    continue  # another worker is mid-flight on this session
                rows = [OutboxRow.from_row(r) for r in db.execute(
                    f"SELECT * FROM sync_outbox WHERE session_id=? AND state='pending' ORDER BY {_RANK_SQL}, id LIMIT 2000",
                    (session_id,))]
                if not rows:
                    continue
                head = _RANK.get(rows[0].entity_type, 1)
                groups: dict[str, list[OutboxRow]] = {}
                if head != 1:
                    groups[rows[0].entity_type] = [rows[0]]
                else:
                    for row in rows:
                        if _RANK.get(row.entity_type, 1) == 1:
                            groups.setdefault(row.entity_type, []).append(row)
                for entity_type, group in groups.items():
                    group.sort(key=lambda r: (r.sequence if r.sequence is not None else r.id, r.id))
                    picked: list[OutboxRow] = []
                    for row in group:  # stop at the first row still backing off: later rows must not overtake it
                        if row.next_attempt_at and row.next_attempt_at > now_s:
                            break
                        picked.append(row)
                        if len(picked) >= max_batch:
                            break
                    if picked:
                        claims.append(Claim(session_id, entity_type, picked))
            ids = [row.id for claim in claims for row in claim.rows]
            if ids:
                db.execute(f"UPDATE sync_outbox SET state='in_flight' WHERE id IN ({','.join('?' * len(ids))})", ids)
        return claims

    def has_due(self, now: datetime | None = None) -> bool:
        with self.store._read() as db:
            row = db.execute("SELECT 1 FROM sync_outbox WHERE state='pending' AND (next_attempt_at IS NULL OR next_attempt_at<=?) LIMIT 1",
                             (ts(now),)).fetchone()
        return row is not None

    # ---- outcomes ------------------------------------------------------------------------------
    def _update(self, ids: Iterable[int], sql: str, params: tuple, guard: str = "state='in_flight'") -> None:
        ids = list(ids)
        if not ids:
            return
        with self.store._tx() as db:
            db.execute(f"UPDATE sync_outbox SET {sql} WHERE {guard} AND id IN ({','.join('?' * len(ids))})", (*params, *ids))

    def mark_synced(self, ids: Iterable[int], note: str | None = None, now: datetime | None = None) -> None:
        self._update(ids, "state='synced', synced_at=?, last_error=?, next_attempt_at=NULL", (ts(now), note))

    def mark_retry(self, ids: Iterable[int], error: str, next_attempt_at: datetime) -> None:
        self._update(ids, "state='pending', attempt_count=attempt_count+1, last_error=?, next_attempt_at=?",
                     (error[:500], ts(next_attempt_at)))

    def mark_failed(self, ids: Iterable[int], error: str) -> None:
        self._update(ids, "state='failed', last_error=?", (error[:500],))

    def release(self, ids: Iterable[int]) -> None:
        """Return claimed rows to ``pending`` untouched (e.g. unauthorized: nothing was wrong with the data)."""
        self._update(ids, "state='pending'", ())

    def reset_in_flight(self) -> int:
        with self.store._tx() as db:
            return db.execute("UPDATE sync_outbox SET state='pending' WHERE state='in_flight'").rowcount

    def retry_failed(self, session_id: str | None = None) -> int:
        with self.store._tx() as db:
            sql = "UPDATE sync_outbox SET state='pending', attempt_count=0, next_attempt_at=NULL WHERE state='failed'"
            args: tuple = ()
            if session_id:
                sql += " AND session_id=?"
                args = (session_id,)
            return db.execute(sql, args).rowcount

    def fail_all_pending(self, reason: str) -> int:
        with self.store._tx() as db:
            return db.execute("UPDATE sync_outbox SET state='failed', last_error=? WHERE state IN ('pending','in_flight')",
                              (reason,)).rowcount

    def requeue_sequences(self, session_id: str, entity_type: str, sequences: Iterable[int]) -> int:
        """Cloud reported gaps for rows we believed synced (e.g. it lost data): send them again."""
        seqs = [int(s) for s in sequences][:500]
        if not seqs:
            return 0
        with self.store._tx() as db:
            return db.execute(
                f"""UPDATE sync_outbox SET state='pending', synced_at=NULL, next_attempt_at=NULL
                    WHERE session_id=? AND entity_type=? AND state='synced' AND sequence IN ({','.join('?' * len(seqs))})""",
                (session_id, entity_type, *seqs)).rowcount

    # ---- introspection ------------------------------------------------------------------------
    def stats(self, session_id: str | None = None) -> dict[str, Any]:
        where, args = ("WHERE session_id=?", (session_id,)) if session_id else ("", ())
        with self.store._read() as db:
            counts = {state: 0 for state in STATES}
            for row in db.execute(f"SELECT state, COUNT(*) FROM sync_outbox {where} GROUP BY state", args):
                counts[row[0]] = row[1]
            oldest = db.execute(f"SELECT MIN(created_at) FROM sync_outbox {where}{' AND' if where else 'WHERE'} state='pending'",
                                args).fetchone()[0]
            last_error = db.execute(
                f"SELECT last_error FROM sync_outbox {where}{' AND' if where else 'WHERE'} last_error IS NOT NULL ORDER BY id DESC LIMIT 1",
                args).fetchone()
        return {**counts, "pending_total": counts["pending"] + counts["in_flight"], "oldest_pending_at": oldest,
                "last_error": last_error[0] if last_error else None}

    def rows(self, state: str | None = None, session_id: str | None = None, limit: int = 1000) -> list[OutboxRow]:
        clauses, args = [], []
        if state:
            clauses.append("state=?"); args.append(state)
        if session_id:
            clauses.append("session_id=?"); args.append(session_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self.store._read() as db:
            return [OutboxRow.from_row(r) for r in db.execute(
                f"SELECT * FROM sync_outbox {where} ORDER BY id LIMIT ?", (*args, limit))]

    # ---- crash safety -------------------------------------------------------------------------
    def reconcile(self, manager, session_id: str) -> int:
        """Re-enqueue anything of ``session_id`` that has no outbox row. Idempotent; returns rows added."""
        from . import payloads

        store = self.store
        session = manager.get_session(session_id)
        observations = store.list_observations(session_id)
        events = store.list_events(session_id, 0, limit=10 ** 9)
        interventions = store.list_interventions(session_id)
        completion = manager.completion_payloads(session_id) if session.status.value == "completed" else None
        added = 0
        with store._tx() as db:
            existing = {(r[0], r[1]) for r in db.execute(
                "SELECT entity_type, entity_id FROM sync_outbox WHERE session_id=?", (session_id,))}

            def add(entity_type: str, entity_id: str, payload: dict[str, Any], sequence: int | None = None) -> None:
                nonlocal added
                if (entity_type, entity_id) not in existing:
                    added += int(enqueue(db, entity_type, entity_id, session_id, payload, sequence))

            add("session", session_id, payloads.session_payload(session))
            for item in observations:
                if item.sequence is not None:
                    add("observation", item.id, payloads.observation_payload(item), item.sequence)
            for item in events:
                add("event", item.event_id, payloads.event_payload(item), item.sequence)
            for item in interventions:
                add("intervention", item.id, payloads.intervention_payload(item))
            if completion:
                for segment in completion["segments"]:
                    add("segment", segment["id"], segment)
                add("summary", session_id, completion["summary"])
                add("stop", session_id, completion["stop"])
        return added

    def reconcile_active(self, manager) -> int:
        """Reconcile every non-finished session (used after login/daemon restart)."""
        from ..models import SessionStatus
        total = 0
        for status in (SessionStatus.ACTIVE, SessionStatus.PAUSED):
            for session in manager.list_sessions(status, 100):
                total += self.reconcile(manager, session.id)
        return total
