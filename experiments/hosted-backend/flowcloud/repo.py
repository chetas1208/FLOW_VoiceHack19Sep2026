"""Repository over SQLAlchemy Core. All tenant scoping (user_id) lives here, not in routes."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, func, insert, or_, select, text, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from . import db as t
from .security import new_id


def now() -> datetime:
    return datetime.now(timezone.utc)


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return utc(value).isoformat() if value else None


TIME_FIELDS = {"created_at", "updated_at", "started_at", "ended_at", "expires_at", "approved_at", "consumed_at",
               "denied_at", "last_seen_at", "revoked_at", "last_login_at", "client_timestamp", "server_received_at",
               "timestamp", "start_at", "end_at", "rotated_at", "last_polled_at", "run_after", "finished_at",
               "requested_at", "resolved_at", "delivered_at", "completed_at", "effective_at", "acked_at", "last_heartbeat_at"}


def row_dict(row: Any) -> dict[str, Any]:
    data = dict(row._mapping)
    for key in TIME_FIELDS & data.keys():
        data[key] = utc(data[key])
    return data


def public_time(data: dict[str, Any]) -> dict[str, Any]:
    return {k: (iso(v) if isinstance(v, datetime) else v) for k, v in data.items()}


class DeviceConflict(Exception):
    pass


class UserConflict(Exception):
    pass


def insert_ignore(conn, table, values: dict[str, Any]) -> bool:  # noqa: ANN001
    """Insert unless any unique constraint already holds the row; True when inserted."""
    dialect = conn.dialect.name
    if dialect == "postgresql":
        stmt = postgresql.insert(table).values(**values).on_conflict_do_nothing()
    else:
        stmt = sqlite.insert(table).values(**values).on_conflict_do_nothing()
    return conn.execute(stmt).rowcount == 1


class Repo:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ---- health / audit -------------------------------------------------------------------
    def ping(self) -> None:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    def audit(self, event: str, *, user_id: str | None = None, device_id: str | None = None,
              ip: str | None = None, detail: dict[str, Any] | None = None) -> None:
        with self.engine.begin() as conn:
            conn.execute(insert(t.audit_events).values(id=new_id("aud"), created_at=now(), user_id=user_id,
                         device_id=device_id, event=event, ip=ip, detail=detail or {}))

    def audit_events(self, user_id: str | None = None, event: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = select(t.audit_events).order_by(t.audit_events.c.created_at.desc()).limit(limit)
        if user_id:
            query = query.where(t.audit_events.c.user_id == user_id)
        if event:
            query = query.where(t.audit_events.c.event == event)
        with self.engine.connect() as conn:
            return [row_dict(r) for r in conn.execute(query)]

    # ---- users -----------------------------------------------------------------------------
    def upsert_user(self, issuer: str, subject: str, email: str, name: str | None) -> dict[str, Any]:
        with self.engine.begin() as conn:
            row = conn.execute(select(t.users).where(and_(t.users.c.issuer == issuer, t.users.c.subject == subject))).first()
            if row:
                conn.execute(update(t.users).where(t.users.c.id == row.id).values(last_login_at=now()))
                return row_dict(row)
            clash = conn.execute(select(t.users.c.id).where(t.users.c.email == email)).first()
            if clash:
                raise UserConflict("email already belongs to another identity")
            values = {"id": new_id("usr"), "email": email, "issuer": issuer, "subject": subject,
                      "display_name": name, "created_at": now(), "last_login_at": now()}
            conn.execute(insert(t.users).values(**values))
            return values

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.users).where(t.users.c.id == user_id)).first()
        return row_dict(row) if row else None

    # ---- devices ---------------------------------------------------------------------------
    def get_device(self, device_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.devices).where(t.devices.c.id == device_id)).first()
        return row_dict(row) if row else None

    def device_status(self, device_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """(device, user) for access-token verification: revoked devices and disabled users fail."""
        with self.engine.connect() as conn:
            row = conn.execute(select(t.devices, t.users.c.disabled_at.label("user_disabled_at"), t.users.c.email)
                               .join(t.users, t.users.c.id == t.devices.c.user_id)
                               .where(t.devices.c.id == device_id)).first()
        if not row:
            return None
        data = row_dict(row)
        return data, {"disabled_at": utc(data.pop("user_disabled_at")), "email": data.pop("email")}

    def upsert_device(self, user_id: str, device_id: str, name: str, os_name: str, arch: str, version: str) -> dict[str, Any]:
        with self.engine.begin() as conn:
            row = conn.execute(select(t.devices).where(t.devices.c.id == device_id)).first()
            if row and row.user_id != user_id:
                raise DeviceConflict("device id belongs to another account")
            if row:
                conn.execute(update(t.devices).where(t.devices.c.id == device_id).values(
                    name=name, os=os_name, architecture=arch, flow_version=version, last_seen_at=now(), revoked_at=None))
            else:
                conn.execute(insert(t.devices).values(id=device_id, user_id=user_id, name=name, os=os_name,
                             architecture=arch, flow_version=version, created_at=now(), last_seen_at=now()))
            return row_dict(conn.execute(select(t.devices).where(t.devices.c.id == device_id)).one())

    def touch_device(self, device_id: str, min_interval: int = 60) -> None:
        cutoff = now() - timedelta(seconds=min_interval)
        with self.engine.begin() as conn:
            conn.execute(update(t.devices).where(and_(t.devices.c.id == device_id, or_(
                t.devices.c.last_seen_at.is_(None), t.devices.c.last_seen_at < cutoff))).values(last_seen_at=now()))

    def list_devices(self, user_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.devices).where(t.devices.c.user_id == user_id)
                                .order_by(t.devices.c.created_at)).all()
        return [row_dict(r) for r in rows]

    def revoke_device(self, user_id: str, device_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(update(t.devices).where(and_(
                t.devices.c.id == device_id, t.devices.c.user_id == user_id)).values(
                revoked_at=func.coalesce(t.devices.c.revoked_at, now())))
            if result.rowcount != 1:
                return False
            conn.execute(update(t.refresh_tokens).where(and_(
                t.refresh_tokens.c.device_id == device_id, t.refresh_tokens.c.revoked_at.is_(None))).values(revoked_at=now()))
        return True

    # ---- CLI auth requests -----------------------------------------------------------------
    def create_auth_request(self, values: dict[str, Any]) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(t.cli_auth_requests).where(and_(
                t.cli_auth_requests.c.device_id == values["device_id"],
                t.cli_auth_requests.c.status == "pending")).values(status="expired"))
            conn.execute(insert(t.cli_auth_requests).values(**values))

    def recent_auth_request_count(self, device_id: str, since: datetime) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(t.cli_auth_requests).where(and_(
                t.cli_auth_requests.c.device_id == device_id, t.cli_auth_requests.c.created_at >= since))).scalar_one())

    def get_auth_request(self, request_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.cli_auth_requests).where(t.cli_auth_requests.c.id == request_id)).first()
        return row_dict(row) if row else None

    def touch_auth_poll(self, request_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(t.cli_auth_requests).where(t.cli_auth_requests.c.id == request_id).values(last_polled_at=now()))

    def set_auth_request_status(self, request_id: str, new: str, *, from_status: str, user_id: str | None = None) -> bool:
        values: dict[str, Any] = {"status": new}
        if new == "approved":
            values.update(user_id=user_id, approved_at=now())
        elif new == "denied":
            values.update(user_id=user_id, denied_at=now())
        elif new == "consumed":
            values.update(consumed_at=now())
        with self.engine.begin() as conn:
            result = conn.execute(update(t.cli_auth_requests).where(and_(
                t.cli_auth_requests.c.id == request_id, t.cli_auth_requests.c.status == from_status)).values(**values))
        return result.rowcount == 1

    def purge_expired_auth_requests(self, older_than: datetime) -> int:
        with self.engine.begin() as conn:
            return conn.execute(delete(t.cli_auth_requests).where(t.cli_auth_requests.c.expires_at < older_than)).rowcount

    # ---- refresh tokens --------------------------------------------------------------------
    def create_refresh_token(self, user_id: str, device_id: str, family_id: str, token_hash: str,
                             expires_at: datetime) -> str:
        token_id = new_id("rt")
        with self.engine.begin() as conn:
            conn.execute(insert(t.refresh_tokens).values(id=token_id, user_id=user_id, device_id=device_id,
                         family_id=family_id, token_hash=token_hash, created_at=now(), expires_at=expires_at))
        return token_id

    def get_refresh_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.refresh_tokens).where(t.refresh_tokens.c.token_hash == token_hash)).first()
        return row_dict(row) if row else None

    def rotate_refresh(self, old_id: str, user_id: str, device_id: str, family_id: str, new_hash: str,
                       expires_at: datetime) -> bool:
        """Atomically spend the old token; False means it was already spent (a replay)."""
        with self.engine.begin() as conn:
            spent = conn.execute(update(t.refresh_tokens).where(and_(
                t.refresh_tokens.c.id == old_id, t.refresh_tokens.c.rotated_at.is_(None),
                t.refresh_tokens.c.revoked_at.is_(None))).values(rotated_at=now()))
            if spent.rowcount != 1:
                return False
            new_id_ = new_id("rt")
            conn.execute(insert(t.refresh_tokens).values(id=new_id_, user_id=user_id, device_id=device_id,
                         family_id=family_id, token_hash=new_hash, created_at=now(), expires_at=expires_at))
            conn.execute(update(t.refresh_tokens).where(t.refresh_tokens.c.id == old_id).values(replaced_by=new_id_))
            conn.execute(update(t.devices).where(t.devices.c.id == device_id).values(last_seen_at=now()))
        return True

    def revoke_family(self, family_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(t.refresh_tokens).where(and_(
                t.refresh_tokens.c.family_id == family_id, t.refresh_tokens.c.revoked_at.is_(None))).values(revoked_at=now()))

    def revoke_device_tokens(self, device_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(t.refresh_tokens).where(and_(
                t.refresh_tokens.c.device_id == device_id, t.refresh_tokens.c.revoked_at.is_(None))).values(revoked_at=now()))

    def purge_expired_refresh_tokens(self, older_than: datetime) -> int:
        with self.engine.begin() as conn:
            return conn.execute(delete(t.refresh_tokens).where(t.refresh_tokens.c.expires_at < older_than)).rowcount

    # ---- sessions --------------------------------------------------------------------------
    def create_session(self, user_id: str, device_id: str, session_id: str, goal: str, started_at: datetime,
                       metadata: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self.engine.begin() as conn:
            created = insert_ignore(conn, t.sessions, {
                "id": session_id, "user_id": user_id, "device_id": device_id, "goal": goal, "status": "active",
                "started_at": started_at, "created_at": now(), "updated_at": now(), "status_sequence": 0,
                "metadata": metadata})
            row = conn.execute(select(t.sessions).where(t.sessions.c.id == session_id)).one()
        data = row_dict(row)
        if data["user_id"] != user_id:
            raise PermissionError("session id conflict")
        return data, created

    def get_session(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        """Tenant-scoped lookup: another user's session is indistinguishable from a missing one."""
        with self.engine.connect() as conn:
            row = conn.execute(select(t.sessions).where(and_(t.sessions.c.id == session_id,
                                                             t.sessions.c.user_id == user_id))).first()
        return row_dict(row) if row else None

    def list_sessions(self, user_id: str, *, status: str | None = None, device_id: str | None = None,
                      since: datetime | None = None, until: datetime | None = None, limit: int = 25,
                      cursor: tuple[datetime, str] | None = None) -> list[dict[str, Any]]:
        query = select(t.sessions).where(t.sessions.c.user_id == user_id)
        if status:
            query = query.where(t.sessions.c.status == status)
        if device_id:
            query = query.where(t.sessions.c.device_id == device_id)
        if since:
            query = query.where(t.sessions.c.started_at >= since)
        if until:
            query = query.where(t.sessions.c.started_at < until)
        if cursor:
            query = query.where(or_(t.sessions.c.started_at < cursor[0], and_(
                t.sessions.c.started_at == cursor[0], t.sessions.c.id < cursor[1])))
        query = query.order_by(t.sessions.c.started_at.desc(), t.sessions.c.id.desc()).limit(limit)
        with self.engine.connect() as conn:
            return [row_dict(r) for r in conn.execute(query)]

    def set_session_status(self, session_id: str, status: str, sequence: int, ended_at: datetime | None = None) -> bool:
        with self.engine.begin() as conn:
            values: dict[str, Any] = {"status": status, "status_sequence": sequence, "updated_at": now()}
            if ended_at:
                values["ended_at"] = ended_at
            result = conn.execute(update(t.sessions).where(and_(
                t.sessions.c.id == session_id, t.sessions.c.status_sequence <= sequence)).values(**values))
        return result.rowcount == 1

    def complete_session(self, session_id: str, ended_at: datetime) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(update(t.sessions).where(and_(t.sessions.c.id == session_id,
                                                       t.sessions.c.status != "completed")).values(
                status="completed", ended_at=ended_at, updated_at=now()))
            return row_dict(conn.execute(select(t.sessions).where(t.sessions.c.id == session_id)).one())

    def update_session_goal(self, session_id: str, goal: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(t.sessions).where(t.sessions.c.id == session_id).values(goal=goal, updated_at=now()))

    # ---- ingestion (idempotent) ------------------------------------------------------------
    def insert_observations(self, session_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Insert in one transaction. Per-item status: created | duplicate | conflict."""
        results = []
        received = now()
        with self.engine.begin() as conn:
            for item in sorted(items, key=lambda i: i["sequence"]):
                values = {**item, "session_id": session_id, "server_received_at": received}
                if insert_ignore(conn, t.observations, values):
                    status = "created"
                else:
                    same = conn.execute(select(t.observations.c.sequence).where(and_(
                        t.observations.c.session_id == session_id, t.observations.c.id == item["id"]))).first()
                    status = "duplicate" if same else "conflict"
                results.append({"id": item["id"], "sequence": item["sequence"], "status": status})
        return results

    def insert_events(self, session_id: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results = []
        received = now()
        with self.engine.begin() as conn:
            for item in sorted(items, key=lambda i: i["sequence"]):
                values = {**item, "session_id": session_id, "server_received_at": received}
                if insert_ignore(conn, t.events, values):
                    status = "created"
                else:
                    same = conn.execute(select(t.events.c.sequence).where(and_(
                        t.events.c.session_id == session_id, t.events.c.event_id == item["event_id"]))).first()
                    status = "duplicate" if same else "conflict"
                results.append({"id": item["event_id"], "sequence": item["sequence"], "status": status})
        return results

    def upsert_segment(self, session_id: str, item: dict[str, Any]) -> str:
        with self.engine.begin() as conn:
            row = conn.execute(select(t.task_segments.c.revision).where(and_(
                t.task_segments.c.session_id == session_id, t.task_segments.c.id == item["id"]))).first()
            if row is None:
                conn.execute(insert(t.task_segments).values(**item, session_id=session_id, updated_at=now()))
                return "created"
            if item["revision"] < row.revision:
                return "stale"
            if item["revision"] == row.revision:
                return "duplicate"
            conn.execute(update(t.task_segments).where(and_(t.task_segments.c.session_id == session_id,
                         t.task_segments.c.id == item["id"])).values(**item, updated_at=now()))
            return "updated"

    def insert_intervention(self, session_id: str, item: dict[str, Any]) -> str:
        with self.engine.begin() as conn:
            if insert_ignore(conn, t.interventions, {**item, "session_id": session_id, "server_received_at": now()}):
                return "created"
            # a delivery update for a known intervention id is a state change, not a duplicate
            conn.execute(update(t.interventions).where(and_(t.interventions.c.session_id == session_id,
                         t.interventions.c.id == item["id"])).values(status=item["status"], message=item["message"]))
            return "duplicate"

    def add_summary(self, session_id: str, summary: dict[str, Any], source: str) -> tuple[int, bool]:
        content_hash = hashlib.sha256(json.dumps(summary, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
        with self.engine.begin() as conn:
            latest = conn.execute(select(t.session_summaries.c.version, t.session_summaries.c.content_hash).where(
                t.session_summaries.c.session_id == session_id).order_by(t.session_summaries.c.version.desc()).limit(1)).first()
            if latest and latest.content_hash == content_hash:
                return latest.version, False
            version = (latest.version if latest else 0) + 1
            conn.execute(insert(t.session_summaries).values(session_id=session_id, version=version, created_at=now(),
                         content_hash=content_hash, source=source, summary=summary))
        return version, True

    # ---- reads -----------------------------------------------------------------------------
    def list_observations(self, session_id: str, after_sequence: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.observations).where(and_(t.observations.c.session_id == session_id,
                t.observations.c.sequence > after_sequence)).order_by(t.observations.c.sequence).limit(limit)).all()
        return [row_dict(r) for r in rows]

    def list_events(self, session_id: str, after_sequence: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.events).where(and_(t.events.c.session_id == session_id,
                t.events.c.sequence > after_sequence)).order_by(t.events.c.sequence).limit(limit)).all()
        return [row_dict(r) for r in rows]

    def latest_event(self, session_id: str, event_type: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.events).where(and_(t.events.c.session_id == session_id,
                t.events.c.type == event_type)).order_by(t.events.c.sequence.desc()).limit(1)).first()
        return row_dict(row) if row else None

    def latest_observation(self, session_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.observations).where(t.observations.c.session_id == session_id)
                               .order_by(t.observations.c.sequence.desc()).limit(1)).first()
        return row_dict(row) if row else None

    def list_segments(self, session_id: str, limit: int = 2000) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.task_segments).where(t.task_segments.c.session_id == session_id)
                                .order_by(t.task_segments.c.start_at).limit(limit)).all()
        return [row_dict(r) for r in rows]

    def list_interventions(self, session_id: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.interventions).where(t.interventions.c.session_id == session_id)
                                .order_by(t.interventions.c.timestamp).limit(limit)).all()
        return [row_dict(r) for r in rows]

    def latest_summary(self, session_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.session_summaries).where(t.session_summaries.c.session_id == session_id)
                               .order_by(t.session_summaries.c.version.desc()).limit(1)).first()
        return row_dict(row) if row else None

    def sequence_state(self, table, session_id: str, limit: int = 100) -> dict[str, Any]:  # noqa: ANN001
        """Highest sequence, row count, and up to `limit` missing sequence numbers."""
        with self.engine.connect() as conn:
            highest, count = conn.execute(select(func.coalesce(func.max(table.c.sequence), 0), func.count()).where(
                table.c.session_id == session_id)).one()
            missing: list[int] = []
            if highest > count:
                have = {r[0] for r in conn.execute(select(table.c.sequence).where(table.c.session_id == session_id))}
                missing = [n for n in range(1, highest + 1) if n not in have][:limit]
        return {"highest_sequence": int(highest), "received": int(count), "missing": missing}

    def count(self, table, session_id: str) -> int:  # noqa: ANN001
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(table).where(table.c.session_id == session_id)).scalar_one())

    # ---- jobs ------------------------------------------------------------------------------
    def enqueue_job(self, job_type: str, payload: dict[str, Any], *, run_after: datetime | None = None,
                    dedupe_key: str | None = None) -> bool:
        with self.engine.begin() as conn:
            return insert_ignore(conn, t.jobs, {"id": new_id("job"), "type": job_type, "payload": payload,
                                 "status": "pending", "attempts": 0, "run_after": run_after or now(),
                                 "created_at": now(), "dedupe_key": dedupe_key})

    def claim_job(self) -> dict[str, Any] | None:
        stmt = select(t.jobs).where(and_(t.jobs.c.status == "pending", t.jobs.c.run_after <= now())) \
            .order_by(t.jobs.c.run_after).limit(1)
        if self.engine.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        with self.engine.begin() as conn:
            row = conn.execute(stmt).first()
            if not row:
                return None
            claimed = conn.execute(update(t.jobs).where(and_(t.jobs.c.id == row.id, t.jobs.c.status == "pending")).values(
                status="running", started_at=now(), attempts=t.jobs.c.attempts + 1))
            if claimed.rowcount != 1:
                return None
        return row_dict(row)

    def finish_job(self, job_id: str, error: str | None = None, retry_in: float | None = None) -> None:
        with self.engine.begin() as conn:
            if error and retry_in is not None:
                conn.execute(update(t.jobs).where(t.jobs.c.id == job_id).values(
                    status="pending", error=error[:1000], run_after=now() + timedelta(seconds=retry_in)))
            else:
                conn.execute(update(t.jobs).where(t.jobs.c.id == job_id).values(
                    status="failed" if error else "done", finished_at=now(), error=(error or None) and error[:1000]))

    def requeue_stale_jobs(self, older_than: timedelta) -> int:
        with self.engine.begin() as conn:
            return conn.execute(update(t.jobs).where(and_(t.jobs.c.status == "running",
                t.jobs.c.started_at < now() - older_than)).values(status="pending")).rowcount

    def job_depth(self) -> int:
        with self.engine.connect() as conn:
            return int(conn.execute(select(func.count()).select_from(t.jobs).where(
                t.jobs.c.status == "pending")).scalar_one())


    # ---- entities (tasks, approvals, recommendations, subtasks, goal versions, chat, runtime state) --
    def upsert_entity(self, session_id: str, kind: str, entity_id: str, revision: int, status: str | None,
                      data: dict[str, Any]) -> str:
        with self.engine.begin() as conn:
            row = conn.execute(select(t.session_entities.c.revision).where(and_(
                t.session_entities.c.session_id == session_id, t.session_entities.c.kind == kind,
                t.session_entities.c.id == entity_id))).first()
            if row is None:
                conn.execute(insert(t.session_entities).values(session_id=session_id, kind=kind, id=entity_id,
                             revision=revision, status=status, data=data, created_at=now(), updated_at=now()))
                return "created"
            if revision < row.revision:
                return "stale"
            if revision == row.revision:
                return "duplicate"
            conn.execute(update(t.session_entities).where(and_(
                t.session_entities.c.session_id == session_id, t.session_entities.c.kind == kind,
                t.session_entities.c.id == entity_id)).values(revision=revision, status=status, data=data, updated_at=now()))
            return "updated"

    def list_entities(self, session_id: str, kind: str | None = None, status: str | None = None,
                      limit: int = 200) -> list[dict[str, Any]]:
        query = select(t.session_entities).where(t.session_entities.c.session_id == session_id)
        if kind:
            query = query.where(t.session_entities.c.kind == kind)
        if status:
            query = query.where(t.session_entities.c.status == status)
        with self.engine.connect() as conn:
            rows = conn.execute(query.order_by(t.session_entities.c.updated_at.desc(), t.session_entities.c.id).limit(limit)).all()
        return [row_dict(r) for r in rows]

    def get_entity(self, session_id: str, kind: str, entity_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.session_entities).where(and_(t.session_entities.c.session_id == session_id,
                t.session_entities.c.kind == kind, t.session_entities.c.id == entity_id))).first()
        return row_dict(row) if row else None

    def pending_approvals(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        query = select(t.session_entities).join(t.sessions, t.sessions.c.id == t.session_entities.c.session_id).where(and_(
            t.sessions.c.user_id == user_id, t.session_entities.c.kind == "approval",
            t.session_entities.c.status == "pending")).order_by(t.session_entities.c.updated_at.desc()).limit(limit)
        with self.engine.connect() as conn:
            return [row_dict(r) for r in conn.execute(query)]

    def set_session_runtime(self, session_id: str, status: str | None = None, goal_version: int | None = None,
                            goal: str | None = None) -> None:
        values: dict[str, Any] = {"updated_at": now()}
        if status:
            values["status"] = status
        if goal_version:
            values["goal_version"] = goal_version
        if goal:
            values["goal"] = goal
        with self.engine.begin() as conn:
            conn.execute(update(t.sessions).where(and_(t.sessions.c.id == session_id,
                                                       t.sessions.c.status != "completed")).values(**values))

    # ---- commands ----------------------------------------------------------------------------
    def create_command(self, values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self.engine.begin() as conn:
            created = insert_ignore(conn, t.commands, values)
            row = conn.execute(select(t.commands).where(t.commands.c.command_id == values["command_id"])).one()
        data = row_dict(row)
        if data["user_id"] != values["user_id"]:
            raise PermissionError("command id conflict")
        return data, created

    def get_command(self, command_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        query = select(t.commands).where(t.commands.c.command_id == command_id)
        if user_id:
            query = query.where(t.commands.c.user_id == user_id)
        with self.engine.connect() as conn:
            row = conn.execute(query).first()
        return row_dict(row) if row else None

    def list_commands(self, user_id: str, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.commands).where(and_(t.commands.c.user_id == user_id,
                t.commands.c.session_id == session_id)).order_by(t.commands.c.created_at.desc()).limit(limit)).all()
        return [row_dict(r) for r in rows]

    def deliverable_commands(self, device_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.commands).where(and_(t.commands.c.device_id == device_id,
                t.commands.c.status.in_(("queued", "delivered")), t.commands.c.expires_at > now()))
                .order_by(t.commands.c.created_at, t.commands.c.command_id)).all()
        return [row_dict(r) for r in rows]

    def expire_commands(self) -> list[dict[str, Any]]:
        """Queued/delivered commands past expiry become `expired`; running ones are left to the device."""
        with self.engine.begin() as conn:
            rows = conn.execute(select(t.commands).where(and_(t.commands.c.status.in_(("queued", "delivered")),
                                                              t.commands.c.expires_at <= now()))).all()
            ids = [r.command_id for r in rows]
            if ids:
                conn.execute(update(t.commands).where(and_(t.commands.c.command_id.in_(ids),
                    t.commands.c.status.in_(("queued", "delivered")))).values(status="expired", completed_at=now()))
        return [{**row_dict(r), "status": "expired"} for r in rows]

    def mark_delivered(self, command_id: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            conn.execute(update(t.commands).where(and_(t.commands.c.command_id == command_id,
                t.commands.c.status.in_(("queued", "delivered")))).values(
                status="delivered", delivered_at=func.coalesce(t.commands.c.delivered_at, now()),
                delivery_count=t.commands.c.delivery_count + 1))
            row = conn.execute(select(t.commands).where(t.commands.c.command_id == command_id)).first()
        return row_dict(row) if row else None

    _COMMAND_ORDER = {"queued": 0, "delivered": 1, "running": 2, "succeeded": 3, "failed": 3, "denied": 3,
                      "expired": 3, "cancelled": 3}

    def ack_command(self, device_id: str, command_id: str, status: str, result: dict[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
        """Forward-only transitions; terminal states are final. Returns (row, changed)."""
        with self.engine.begin() as conn:
            row = conn.execute(select(t.commands).where(and_(t.commands.c.command_id == command_id,
                                                             t.commands.c.device_id == device_id))).first()
            if row is None:
                return None, False
            if self._COMMAND_ORDER[status] <= self._COMMAND_ORDER[row.status] or row.status in {
                    "succeeded", "failed", "denied", "expired", "cancelled"}:
                return row_dict(row), False
            values: dict[str, Any] = {"status": status, "acked_at": func.coalesce(t.commands.c.acked_at, now())}
            if result is not None:
                values["result"] = result
            if self._COMMAND_ORDER[status] == 3:
                values["completed_at"] = now()
            conn.execute(update(t.commands).where(t.commands.c.command_id == command_id).values(**values))
            row = conn.execute(select(t.commands).where(t.commands.c.command_id == command_id)).one()
        return row_dict(row), True

    # ---- device presence -----------------------------------------------------------------------
    def presence_seen(self, device_id: str, connection_id: str | None, health: dict[str, Any],
                      active_sessions: list[str], flow_version: str | None = None, connected: bool = True) -> None:
        values = {"connection_id": connection_id, "connected": connected, "last_heartbeat_at": now(), "health": health,
                  "active_sessions": active_sessions, "flow_version": flow_version, "updated_at": now()}
        with self.engine.begin() as conn:
            updated = conn.execute(update(t.device_presence).where(t.device_presence.c.device_id == device_id).values(**values))
            if updated.rowcount == 0:
                conn.execute(insert(t.device_presence).values(device_id=device_id, **values))

    def presence_disconnect(self, device_id: str, connection_id: str) -> bool:
        with self.engine.begin() as conn:
            result = conn.execute(update(t.device_presence).where(and_(t.device_presence.c.device_id == device_id,
                t.device_presence.c.connection_id == connection_id)).values(connected=False, updated_at=now()))
        return result.rowcount == 1

    def get_presence(self, device_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(t.device_presence).where(t.device_presence.c.device_id == device_id)).first()
        return row_dict(row) if row else None

    def presence_map(self, device_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not device_ids:
            return {}
        with self.engine.connect() as conn:
            rows = conn.execute(select(t.device_presence).where(t.device_presence.c.device_id.in_(device_ids))).all()
        return {r.device_id: row_dict(r) for r in rows}


__all__ = ["Repo", "DeviceConflict", "UserConflict", "IntegrityError", "iso", "now", "utc", "row_dict", "public_time"]
