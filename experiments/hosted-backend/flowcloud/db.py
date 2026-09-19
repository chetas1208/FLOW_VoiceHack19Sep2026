"""SQLAlchemy Core schema shared by SQLite (tests/dev) and PostgreSQL (production)."""

from __future__ import annotations

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, MetaData,
                        String, Table, Text, UniqueConstraint, create_engine, event)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

metadata = MetaData(naming_convention={
    "ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s"})

Json = JSON().with_variant(JSONB(), "postgresql")
TS = DateTime(timezone=True)

users = Table("users", metadata,
    Column("id", String(40), primary_key=True), Column("email", String(320), nullable=False, unique=True),
    Column("issuer", String(300)), Column("subject", String(300)), Column("display_name", String(200)),
    Column("created_at", TS, nullable=False), Column("last_login_at", TS), Column("disabled_at", TS),
    UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"))

devices = Table("devices", metadata,
    Column("id", String(64), primary_key=True), Column("user_id", String(40), ForeignKey("users.id"), nullable=False),
    Column("name", String(200), nullable=False), Column("os", String(50), nullable=False),
    Column("architecture", String(50), nullable=False), Column("flow_version", String(40), nullable=False),
    Column("created_at", TS, nullable=False), Column("last_seen_at", TS), Column("revoked_at", TS),
    Index("ix_devices_user_id", "user_id"))

cli_auth_requests = Table("cli_auth_requests", metadata,
    Column("id", String(64), primary_key=True), Column("device_id", String(64), nullable=False),
    Column("device_name", String(200), nullable=False), Column("device_os", String(50), nullable=False),
    Column("device_arch", String(50), nullable=False), Column("flow_version", String(40), nullable=False),
    Column("code_challenge", String(128), nullable=False), Column("state", String(200), nullable=False),
    Column("nonce", String(200), nullable=False), Column("user_code", String(16), nullable=False),
    Column("status", String(16), nullable=False), Column("user_id", String(40), ForeignKey("users.id")),
    Column("created_at", TS, nullable=False), Column("expires_at", TS, nullable=False),
    Column("approved_at", TS), Column("consumed_at", TS), Column("denied_at", TS), Column("last_polled_at", TS),
    Index("ix_cli_auth_requests_device_id", "device_id"), Index("ix_cli_auth_requests_expires_at", "expires_at"))

refresh_tokens = Table("refresh_tokens", metadata,
    Column("id", String(40), primary_key=True), Column("user_id", String(40), ForeignKey("users.id"), nullable=False),
    Column("device_id", String(64), ForeignKey("devices.id"), nullable=False),
    Column("family_id", String(40), nullable=False), Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_at", TS, nullable=False), Column("expires_at", TS, nullable=False),
    Column("rotated_at", TS), Column("revoked_at", TS), Column("replaced_by", String(40)),
    Index("ix_refresh_tokens_device_id", "device_id"), Index("ix_refresh_tokens_family_id", "family_id"))

sessions = Table("sessions", metadata,
    Column("id", String(80), primary_key=True), Column("user_id", String(40), ForeignKey("users.id"), nullable=False),
    Column("device_id", String(64), ForeignKey("devices.id"), nullable=False),
    Column("goal", Text, nullable=False), Column("status", String(32), nullable=False),
    Column("goal_version", Integer, nullable=False, server_default="1"),
    Column("started_at", TS, nullable=False), Column("ended_at", TS),
    Column("created_at", TS, nullable=False), Column("updated_at", TS, nullable=False),
    Column("status_sequence", Integer, nullable=False, server_default="0"),
    Column("metadata", Json, nullable=False),
    Index("ix_sessions_user_id_started_at", "user_id", "started_at"),
    Index("ix_sessions_device_id", "device_id"))

observations = Table("observations", metadata,
    Column("session_id", String(80), ForeignKey("sessions.id"), primary_key=True),
    Column("id", String(80), primary_key=True), Column("sequence", Integer, nullable=False),
    Column("client_timestamp", TS, nullable=False), Column("server_received_at", TS, nullable=False),
    Column("activity", Text), Column("category", String(24), nullable=False),
    Column("goal_alignment", Float), Column("progress_signal", Float), Column("confidence", Float),
    Column("task_phase", String(40)), Column("application", String(200)), Column("activity_type", String(40)),
    Column("source", String(40), nullable=False), Column("blocker", String(200)),
    UniqueConstraint("session_id", "sequence", name="uq_observations_session_sequence"),
    Index("ix_observations_session_id_sequence", "session_id", "sequence"))

events = Table("events", metadata,
    Column("session_id", String(80), ForeignKey("sessions.id"), primary_key=True),
    Column("event_id", String(80), primary_key=True), Column("sequence", Integer, nullable=False),
    Column("type", String(48), nullable=False), Column("client_timestamp", TS, nullable=False),
    Column("server_received_at", TS, nullable=False), Column("data", Json, nullable=False),
    UniqueConstraint("session_id", "sequence", name="uq_events_session_sequence"),
    Index("ix_events_session_id_sequence", "session_id", "sequence"),
    Index("ix_events_session_id_type_sequence", "session_id", "type", "sequence"))

task_segments = Table("task_segments", metadata,
    Column("session_id", String(80), ForeignKey("sessions.id"), primary_key=True),
    Column("id", String(80), primary_key=True), Column("start_at", TS, nullable=False), Column("end_at", TS, nullable=False),
    Column("activity", Text), Column("category", String(24), nullable=False), Column("application", String(200)),
    Column("alignment", Float), Column("confidence", Float), Column("observation_count", Integer, nullable=False),
    Column("revision", Integer, nullable=False, server_default="1"), Column("updated_at", TS, nullable=False),
    Index("ix_task_segments_session_id_start_at", "session_id", "start_at"))

interventions = Table("interventions", metadata,
    Column("session_id", String(80), ForeignKey("sessions.id"), primary_key=True),
    Column("id", String(80), primary_key=True), Column("timestamp", TS, nullable=False),
    Column("reason", String(100), nullable=False), Column("channel", String(16), nullable=False),
    Column("message", Text), Column("status", String(16), nullable=False), Column("metadata", Json, nullable=False),
    Column("server_received_at", TS, nullable=False),
    Index("ix_interventions_session_id_timestamp", "session_id", "timestamp"))

session_summaries = Table("session_summaries", metadata,
    Column("session_id", String(80), ForeignKey("sessions.id"), primary_key=True),
    Column("version", Integer, primary_key=True), Column("created_at", TS, nullable=False),
    Column("content_hash", String(64), nullable=False), Column("source", String(24), nullable=False),
    Column("summary", Json, nullable=False))

commands = Table("commands", metadata,
    Column("command_id", String(80), primary_key=True), Column("user_id", String(40), ForeignKey("users.id"), nullable=False),
    Column("device_id", String(64), ForeignKey("devices.id"), nullable=False), Column("session_id", String(80)),
    Column("source", String(16), nullable=False), Column("type", String(40), nullable=False),
    Column("payload", Json, nullable=False), Column("status", String(16), nullable=False), Column("result", Json),
    Column("created_at", TS, nullable=False), Column("expires_at", TS, nullable=False),
    Column("delivered_at", TS), Column("acked_at", TS), Column("completed_at", TS),
    Column("delivery_count", Integer, nullable=False, server_default="0"),
    Index("ix_commands_device_id_status_created_at", "device_id", "status", "created_at"),
    Index("ix_commands_session_id_created_at", "session_id", "created_at"),
    Index("ix_commands_user_id_created_at", "user_id", "created_at"))

device_presence = Table("device_presence", metadata,
    Column("device_id", String(64), ForeignKey("devices.id"), primary_key=True),
    Column("connection_id", String(64)), Column("connected", Boolean, nullable=False, server_default="0"),
    Column("last_heartbeat_at", TS), Column("health", Json, nullable=False), Column("active_sessions", Json, nullable=False),
    Column("flow_version", String(40)), Column("updated_at", TS, nullable=False))

session_entities = Table("session_entities", metadata,
    Column("session_id", String(80), ForeignKey("sessions.id"), primary_key=True),
    Column("kind", String(24), primary_key=True), Column("id", String(80), primary_key=True),
    Column("revision", Integer, nullable=False), Column("status", String(24)), Column("data", Json, nullable=False),
    Column("created_at", TS, nullable=False), Column("updated_at", TS, nullable=False),
    Index("ix_session_entities_session_id_kind_updated_at", "session_id", "kind", "updated_at"),
    Index("ix_session_entities_kind_status", "kind", "status"))

audit_events = Table("audit_events", metadata,
    Column("id", String(40), primary_key=True), Column("created_at", TS, nullable=False),
    Column("user_id", String(40)), Column("device_id", String(64)), Column("event", String(60), nullable=False),
    Column("ip", String(64)), Column("detail", Json, nullable=False),
    Index("ix_audit_events_user_id_created_at", "user_id", "created_at"),
    Index("ix_audit_events_event_created_at", "event", "created_at"))

jobs = Table("jobs", metadata,
    Column("id", String(40), primary_key=True), Column("type", String(40), nullable=False),
    Column("payload", Json, nullable=False), Column("status", String(12), nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"), Column("run_after", TS, nullable=False),
    Column("created_at", TS, nullable=False), Column("started_at", TS), Column("finished_at", TS),
    Column("error", Text), Column("dedupe_key", String(120), unique=True),
    Index("ix_jobs_status_run_after", "status", "run_after"))

def make_engine(url: str) -> Engine:
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_connection, _record):  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON"); cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000"); cursor.close()
        return engine
    return create_engine(url, pool_size=10, max_overflow=20, pool_pre_ping=True, pool_recycle=1800)
