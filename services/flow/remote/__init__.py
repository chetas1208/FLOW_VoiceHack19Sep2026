"""Remote operating layer: one command path for the CLI (local IPC) and the web (cloud WebSocket).

Modules import lazily so ``services.flow.remote.ipc_protocol`` (used by tiny CLI clients) stays cheap.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "CommandDispatcher": "dispatcher", "CommandResult": "dispatcher", "CommandRejected": "dispatcher",
    "DeviceChannel": "channel", "LocalCommands": "local_commands", "LocalLedger": "ledger",
    "build_health": "presence", "presence_snapshot": "presence",
}
__all__ = sorted(_EXPORTS)


def __getattr__(name: str):
    if name in _EXPORTS:
        return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
    raise AttributeError(name)
