"""flow-worker: durable, non-latency-sensitive jobs (summary fallback, housekeeping)."""

from __future__ import annotations

import asyncio
import logging
import random
import signal
from datetime import timedelta
from typing import Any, Callable

from . import views
from .app import build_cloud
from .core import Cloud
from .observability import configure_logging, span
from .repo import now
from .routes_remote import sweep_expired
from .settings import Settings

log = logging.getLogger("flow.worker")
MAX_ATTEMPTS = 5


def job_ensure_summary(cloud: Cloud, payload: dict[str, Any]) -> None:
    """Build a cloud-derived summary only when the device never uploaded one."""
    repo = cloud.repo
    session_id = payload["session_id"]
    with repo.engine.connect() as conn:
        from sqlalchemy import select
        from . import db
        row = conn.execute(select(db.sessions).where(db.sessions.c.id == session_id)).first()
    if row is None or repo.latest_summary(session_id):
        return
    session = dict(row._mapping)
    from .repo import utc
    for key in ("started_at", "ended_at", "created_at", "updated_at"):
        session[key] = utc(session[key])
    repo.add_summary(session_id, views.derive_summary(repo, session), "cloud")


def job_housekeeping(cloud: Cloud, payload: dict[str, Any]) -> None:
    cutoff = now() - timedelta(days=7)
    cloud.repo.purge_expired_auth_requests(cutoff)
    cloud.repo.purge_expired_refresh_tokens(now() - timedelta(days=30))
    sweep_expired(cloud)


HANDLERS: dict[str, Callable[[Cloud, dict[str, Any]], None]] = {"ensure_summary": job_ensure_summary,
                                                                 "housekeeping": job_housekeeping}


def run_one(cloud: Cloud) -> bool:
    job = cloud.repo.claim_job()
    if job is None:
        return False
    handler = HANDLERS.get(job["type"])
    try:
        if handler is None:
            raise ValueError(f"unknown job type {job['type']}")
        with span("job." + job["type"], attempt=job["attempts"] + 1):
            handler(cloud, job["payload"])
        cloud.repo.finish_job(job["id"])
        cloud.metrics.inc("flow_jobs_total", type=job["type"], outcome="done")
    except Exception as exc:
        attempts = job["attempts"] + 1
        retry = min(300.0, 2.0 ** attempts) if attempts < MAX_ATTEMPTS else None
        cloud.repo.finish_job(job["id"], error=f"{type(exc).__name__}: {exc}", retry_in=retry)
        cloud.metrics.inc("flow_jobs_total", type=job["type"], outcome="failed")
        log.warning("job failed", extra={"fields": {"job_type": job["type"], "attempts": attempts}})
    return True


async def run(cloud: Cloud, stop: asyncio.Event, interval: float = 2.0) -> None:
    last_housekeeping = 0.0
    loop = asyncio.get_running_loop()
    while not stop.is_set():
        worked = await asyncio.to_thread(run_one, cloud)
        if loop.time() - last_housekeeping > 600:
            last_housekeeping = loop.time()
            await asyncio.to_thread(cloud.repo.enqueue_job, "housekeeping", {}, dedupe_key=f"hk:{int(loop.time() // 600)}")
            await asyncio.to_thread(cloud.repo.requeue_stale_jobs, timedelta(minutes=10))
        if not worked:
            try:
                await asyncio.wait_for(stop.wait(), interval + random.random())
            except asyncio.TimeoutError:
                pass


def main() -> int:
    settings = Settings.from_env().validate()
    configure_logging(settings.log_level)
    cloud = build_cloud(settings)
    stop = asyncio.Event()

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        log.info("worker started")
        await run(cloud, stop)
        cloud.repo.engine.dispose()
        log.info("worker stopped")

    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
