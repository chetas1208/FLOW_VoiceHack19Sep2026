"""Minimal authenticated-by-filesystem local daemon IPC."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any

from .config import config_dir


def socket_path() -> Path:
    return config_dir() / "flow.sock"


def pid_path() -> Path:
    return config_dir() / "flow.pid"


class FlowDaemon:
    def __init__(self, socket: Path | None = None) -> None:
        self.socket = socket or socket_path()
        self.pid = self.socket.with_name("flow.pid")
        self.server: asyncio.AbstractServer | None = None

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5)
            request = json.loads(raw)
            if request.get("command") == "ping":
                response = {"status": "ok", "pid": os.getpid()}
            elif request.get("command") == "status":
                response = {"status": "running", "pid": os.getpid()}
            else:
                response = {"status": "error", "error": "unsupported command"}
            writer.write((json.dumps(response) + "\n").encode()); await writer.drain()
        except (asyncio.TimeoutError, json.JSONDecodeError):
            writer.write(b'{"status":"error","error":"invalid request"}\n'); await writer.drain()
        finally:
            writer.close(); await writer.wait_closed()

    async def run(self) -> None:
        self.socket.parent.mkdir(parents=True, exist_ok=True)
        self.socket.unlink(missing_ok=True)
        self.server = await asyncio.start_unix_server(self.handle, path=self.socket)
        self.socket.chmod(0o600)
        self.pid.write_text(str(os.getpid())); self.pid.chmod(0o600)
        try:
            async with self.server:
                await self.server.serve_forever()
        finally:
            self.socket.unlink(missing_ok=True); self.pid.unlink(missing_ok=True)


async def request(command: str, socket: Path | None = None) -> dict[str, Any]:
    path = socket or socket_path()
    reader, writer = await asyncio.open_unix_connection(path)
    writer.write((json.dumps({"command": command}) + "\n").encode()); await writer.drain()
    result = json.loads(await reader.readline())
    writer.close(); await writer.wait_closed()
    return result


def run_daemon() -> None:
    asyncio.run(FlowDaemon().run())


if __name__ == "__main__":
    run_daemon()
