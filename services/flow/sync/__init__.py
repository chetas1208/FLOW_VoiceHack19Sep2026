"""Cloud sync: transactional outbox, upload payload builders, and the asyncio ``SyncWorker``.

Imports are lazy so ``services.flow.store`` can use ``sync.outbox``/``sync.payloads`` without a cycle.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "SyncOutbox": "outbox", "OutboxRow": "outbox", "Claim": "outbox",
    "SyncWorker": "worker", "SyncWorkerBusy": "worker",
    "cloud_sync_enabled": "state", "read_sync_status": "state", "SYNC_STATE_KEY": "state",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
    raise AttributeError(name)
