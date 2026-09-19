"""``SyncWorker``: drains the outbox to the cloud, independently of observation and analysis.

Guarantees
* a row is marked ``synced`` only after the cloud answered 2xx (uploads are idempotent by id, so re-sending after
  a crash is safe);
* per session the ``session`` row goes first, ``summary``/``stop`` last, and each kind is sent in sequence order;
* transient failures (network, 5xx, 429) back off exponentially with jitter (capped, 5 min) and never drop data;
* permanent 4xx rows are marked ``failed`` (with the reason) and the queue moves on; a rejected batch is bisected
  so one bad row cannot take 99 good ones with it;
* ``CloudUnauthorized`` pauses uploads (``unauthorized``/``signed_out``) without touching the local session and
  resumes by itself once ``flow login`` stores new credentials;
* enqueueing wakes the worker immediately (same-process callback), other processes are noticed within ``interval``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..cloud.client import CloudClient
from ..cloud.errors import CloudError, CloudRejected, CloudUnauthorized, CloudUnavailable
from ..store import FlowStore
from .outbox import Claim, OutboxRow, SyncOutbox, ts
from .state import SYNC_STATE_KEY, UNAUTHORIZED_MESSAGE

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger("flow.sync")
BATCH_TYPES = {"observation", "event", "entity"}


class SyncWorkerBusy(RuntimeError):
    """Another process already runs the sync worker for this data directory."""


class SyncWorker:
    def __init__(self, store: FlowStore, client: CloudClient, *, interval: float = 1.0, base_backoff: float = 1.0,
                 max_backoff: float = 300.0, batch_size: int = 100, unauthorized_poll: float = 2.0,
                 heartbeat_seconds: float = 10.0, rng: Callable[[], float] = random.random,
                 clock: Callable[[], datetime] | None = None,
                 on_message: Callable[[str], None] | None = None) -> None:
        self.store, self.client, self.outbox = store, client, SyncOutbox(store)
        self.interval, self.base_backoff, self.max_backoff = interval, base_backoff, max_backoff
        self.batch_size, self.unauthorized_poll, self.heartbeat_seconds = batch_size, unauthorized_poll, heartbeat_seconds
        self.rng = rng
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.on_message = on_message or (lambda text: log.warning(text))
        self.state, self.message, self.last_error = "idle", None, None
        self.last_sync_at: str | None = None
        self.stats = {"synced": 0, "failed": 0, "retried": 0}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._stop = False
        self._lock_fd: int | None = None
        self._last_write = 0.0
        self._paused_fingerprint: str | None = None

    # ---- wake / lifecycle ----------------------------------------------------------------------
    def attach(self, store: FlowStore | None = None) -> "SyncWorker":
        """Wake this worker as soon as anything is queued through ``store`` (default: the worker's own)."""
        (store or self.store).on_enqueue(self.wake)
        return self

    def wake(self) -> None:
        """Thread-safe. Safe to call before ``run`` starts."""
        loop, event = self._loop, self._wake
        if loop is not None and event is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:  # loop shutting down
                pass

    def stop(self) -> None:
        self._stop = True
        self.wake()

    def acquire(self) -> bool:
        """Take the per-data-dir worker lock (False if another process runs a worker). ``release`` drops it."""
        return self._acquire_lock()

    def release(self) -> None:
        self._release_lock()

    def _acquire_lock(self) -> bool:
        if fcntl is None:  # pragma: no cover
            return True
        fd = os.open(self.store.root / "sync-worker.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self._lock_fd = fd
        return True

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            try:
                os.close(self._lock_fd)  # closing drops the flock
            finally:
                self._lock_fd = None

    async def run(self) -> None:
        """Run until ``stop()``. Raises ``SyncWorkerBusy`` if another process already runs one for this store."""
        if not self._acquire_lock():
            raise SyncWorkerBusy(f"another FLOW process is already syncing {self.store.root}")
        self._loop, self._wake, self._stop = asyncio.get_running_loop(), asyncio.Event(), False
        try:
            await asyncio.to_thread(self.outbox.reset_in_flight)  # rows a crashed worker left mid-upload
            while not self._stop:
                if self.state in {"unauthorized", "signed_out"}:
                    await self._wait_for_login()
                    continue
                if await asyncio.to_thread(self.outbox.has_due, self.clock()):
                    result = await self.run_once()
                    if result["claimed"] and not (result["retried"] or self.state in {"unauthorized", "signed_out"}):
                        await self._persist_state()
                        continue  # more may be due: go straight round
                await self._persist_state()
                await self._sleep(self.interval)
        finally:
            self.state = "stopped"
            await asyncio.to_thread(self._write_state, True)
            self._release_lock()
            self._loop = self._wake = None

    async def _sleep(self, seconds: float) -> None:
        event = self._wake
        if event is None:
            await asyncio.sleep(seconds)
            return
        try:
            await asyncio.wait_for(event.wait(), seconds)
        except asyncio.TimeoutError:
            pass
        event.clear()

    async def _wait_for_login(self) -> None:
        await self._persist_state()
        await self._sleep(self.unauthorized_poll)
        if self.client.tokens.fingerprint() != self._paused_fingerprint:
            self._set_state("idle", None)  # credentials changed (flow login): try again right away

    # ---- state ---------------------------------------------------------------------------------
    def _set_state(self, state: str, message: str | None, error: str | None = None) -> None:
        changed = state != self.state
        self.state, self.message = state, message
        if error:
            self.last_error = error
        if changed and message:
            self.on_message(message)
        if changed:
            self._last_write = 0.0

    def _write_state(self, force: bool = False) -> None:
        import time
        if not force and time.monotonic() - self._last_write < self.heartbeat_seconds:
            return
        self._last_write = time.monotonic()
        self.store.set_state(SYNC_STATE_KEY, {
            "state": self.state, "message": self.message, "last_error": self.last_error,
            "last_sync_at": self.last_sync_at, "pid": os.getpid(), "heartbeat_at": datetime.now(timezone.utc).isoformat()})

    async def _persist_state(self) -> None:
        await asyncio.to_thread(self._write_state, False)

    # ---- one pass ------------------------------------------------------------------------------
    async def run_once(self) -> dict[str, int]:
        """Claim and send everything due. Returns counters; never raises for cloud/transport problems."""
        counters = {"claimed": 0, "synced": 0, "failed": 0, "retried": 0}
        await asyncio.to_thread(self._check_owner)
        claims = await asyncio.to_thread(self.outbox.claim_batches, self.clock(), self.batch_size)
        counters["claimed"] = sum(len(claim.rows) for claim in claims)
        for index, claim in enumerate(claims):
            try:
                await self._send(claim, counters)
            except CloudUnauthorized as exc:
                await asyncio.to_thread(self.outbox.release, [row.id for c in claims[index:] for row in c.rows])
                self._paused_fingerprint = self.client.tokens.fingerprint()
                if self.client.tokens.has_credentials():
                    self._set_state("unauthorized", UNAUTHORIZED_MESSAGE, str(exc))
                else:
                    self._set_state("signed_out", "Not signed in. Run flow login to sync to FLOW cloud.", str(exc))
                break
            except CloudUnavailable as exc:
                await asyncio.to_thread(self._retry_rows, claims[index].rows, exc)
                later = [row.id for c in claims[index + 1:] for row in c.rows]
                await asyncio.to_thread(self.outbox.release, later)
                counters["retried"] += len(claims[index].rows)
                self.stats["retried"] += len(claims[index].rows)
                self._set_state("offline", f"FLOW cloud unreachable; will retry ({exc}).", str(exc))
                break
            except CloudError as exc:  # unexpected shape from the cloud: treat as transient, never lose data
                await asyncio.to_thread(self._retry_rows, claim.rows, exc)
                counters["retried"] += len(claim.rows)
                self.last_error = str(exc)
        if counters["synced"] and self.state != "connected":
            self._set_state("connected", None)
        if counters["synced"]:
            self.last_sync_at = datetime.now(timezone.utc).isoformat()
        return counters

    async def drain(self, max_passes: int = 1000) -> dict[str, int]:
        """Send until nothing is due (or the cloud stops answering). Handy for ``flow sync`` and tests."""
        total = {"claimed": 0, "synced": 0, "failed": 0, "retried": 0}
        for _ in range(max_passes):
            result = await self.run_once()
            for key in total:
                total[key] += result[key]
            if not result["claimed"] or result["retried"] or self.state in {"unauthorized", "signed_out"}:
                break
        await asyncio.to_thread(self._write_state, True)
        return total

    def _check_owner(self) -> None:
        """Never upload a previous account's queued history to a different account after re-login."""
        bundle = self.client.credentials.load_bundle() or {}
        user_id = (bundle.get("user") or {}).get("id")
        if not user_id:
            return
        owner = self.store.get_state("outbox_owner").get("user_id")
        if owner and owner != user_id:
            dropped = self.outbox.fail_all_pending("account changed since these rows were queued")
            if dropped:
                log.warning("dropped %s queued uploads that belonged to a different FLOW account", dropped)
        if owner != user_id:
            self.store.set_state("outbox_owner", {"user_id": user_id})

    # ---- delivery ------------------------------------------------------------------------------
    def _backoff(self, attempt: int, retry_after: float | None = None) -> datetime:
        delay = min(self.max_backoff, self.base_backoff * (2 ** min(attempt, 20)))
        delay = delay * (0.5 + 0.5 * self.rng())  # jitter: 50-100% of the exponential step
        if retry_after:
            delay = max(delay, min(retry_after, self.max_backoff))
        return self.clock() + timedelta(seconds=delay)

    def _retry_rows(self, rows: list[OutboxRow], exc: Exception) -> None:
        attempt = max((row.attempt_count for row in rows), default=0)
        self.outbox.mark_retry([row.id for row in rows], str(exc), self._backoff(attempt, getattr(exc, "retry_after", None)))

    async def _send(self, claim: Claim, counters: dict[str, int]) -> None:
        rows, kind, sid = claim.rows, claim.entity_type, claim.session_id
        if kind in BATCH_TYPES:
            await self._deliver_batch(kind, sid, rows, counters)
            return
        for row in rows:  # single-item endpoints, strictly in order
            try:
                response = await self._call_single(kind, sid, row)
            except CloudRejected as exc:
                await asyncio.to_thread(self.outbox.mark_failed, [row.id], f"{exc.status} {exc.code}: {exc}")
                counters["failed"] += 1
                self.stats["failed"] += 1
                continue
            note = "conflict" if isinstance(response, dict) and response.get("status") == "conflict" else None
            await asyncio.to_thread(self.outbox.mark_synced, [row.id], note)
            counters["synced"] += 1
            self.stats["synced"] += 1

    async def _call_single(self, kind: str, session_id: str, row: OutboxRow) -> Any:
        client = self.client
        if kind == "session":
            return await client.create_session(row.payload)
        if kind == "intervention":
            return await client.post_intervention(session_id, row.payload)
        if kind == "segment":
            return await client.post_segment(session_id, row.payload)
        if kind == "summary":
            return await client.put_summary(session_id, row.payload)
        if kind == "stop":
            return await client.stop_session(session_id, ended_at=row.payload.get("ended_at"))
        raise CloudRejected(f"unknown outbox entity type {kind!r}", status=0, code="unknown_entity_type")

    async def _call_batch(self, kind: str, session_id: str, rows: list[OutboxRow]) -> Any:
        payloads = [row.payload for row in rows]
        if kind == "observation":
            return await (self.client.post_observation(session_id, payloads[0]) if len(rows) == 1
                          else self.client.post_observations(session_id, payloads))
        if kind == "event":
            return await (self.client.post_event(session_id, payloads[0]) if len(rows) == 1
                          else self.client.post_events(session_id, payloads))
        return await self.client.post_entities(session_id, payloads)

    async def _deliver_batch(self, kind: str, session_id: str, rows: list[OutboxRow], counters: dict[str, int]) -> None:
        try:
            response = await self._call_batch(kind, session_id, rows)
        except CloudRejected as exc:
            if len(rows) > 1:  # isolate the poison row(s) by bisection
                middle = len(rows) // 2
                await self._deliver_batch(kind, session_id, rows[:middle], counters)
                await self._deliver_batch(kind, session_id, rows[middle:], counters)
                return
            await asyncio.to_thread(self.outbox.mark_failed, [rows[0].id], f"{exc.status} {exc.code}: {exc}")
            counters["failed"] += 1
            self.stats["failed"] += 1
            return
        conflicts = {item.get("id") for item in (response or {}).get("results", []) if item.get("status") == "conflict"} \
            if isinstance(response, dict) else set()
        ok = [row.id for row in rows if row.entity_id not in conflicts]
        await asyncio.to_thread(self.outbox.mark_synced, ok)
        if conflicts:
            await asyncio.to_thread(self.outbox.mark_synced, [r.id for r in rows if r.entity_id in conflicts], "conflict")
        counters["synced"] += len(rows)
        self.stats["synced"] += len(rows)
        await self._repair_gaps(kind, session_id, response)

    async def _repair_gaps(self, kind: str, session_id: str, response: Any) -> None:
        """The cloud lists sequences it is missing below its highest: resend the ones we believed synced."""
        missing = ((response or {}).get("sync") or {}).get("missing") if isinstance(response, dict) else None
        if missing and kind in {"observation", "event"}:
            await asyncio.to_thread(self.outbox.requeue_sequences, session_id, kind, missing)
