"""Minimal authenticated-by-filesystem local daemon IPC."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any

from .config import config_dir
from .session_manager import InvalidTransition, SessionManager, SessionNotFound


def socket_path() -> Path:
    return config_dir() / "flow.sock"


def pid_path() -> Path:
    return config_dir() / "flow.pid"


class FlowDaemon:
    def __init__(self, socket: Path | None = None, manager: SessionManager | None = None) -> None:
        self.socket = socket or socket_path()
        self.pid = self.socket.with_name("flow.pid")
        self.server: asyncio.AbstractServer | None = None
        self.manager = manager or SessionManager.from_environment()
        self.session_id: str | None = None

    def _command(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        """Handle lifecycle commands in the daemon process.

        Observer/model workers are deliberately not started on a command
        socket request; they are optional capabilities and report their own
        readiness through status instead of making session control fail.
        """
        if command == "ping":
            return {"status": "ok", "pid": os.getpid()}
        if command in {"status", "session.status"}:
            session = self.manager.get_session(self.session_id) if self.session_id else None
            return {"status": "running", "pid": os.getpid(),
                    "session": session.to_dict() if session else None}
        if command == "session.start":
            goal = str(args.get("goal") or "").strip()
            if not goal:
                raise ValueError("session.start requires a goal")
            if self.session_id:
                raise ValueError("a FLOW session is already active")
            session = self.manager.start_session(goal, metadata={"daemon_pid": os.getpid()})
            self.session_id = session.id
            return {"session": session.to_dict()}
        if command in {"session.stop", "session.pause", "session.resume"}:
            session_id = str(args.get("session_id") or self.session_id or "")
            if not session_id:
                raise SessionNotFound("no active FLOW session")
            action = {"session.stop": self.manager.stop_session,
                      "session.pause": self.manager.pause_session,
                      "session.resume": self.manager.resume_session}[command]
            session = action(session_id)
            if command == "session.stop" and session_id == self.session_id:
                self.session_id = None
            return {"session": session.to_dict()}
        if command == "session.list":
            return {"sessions": [session.to_dict() for session in self.manager.list_sessions()]}
        if command == "shutdown":
            if self.server:
                self.server.close()
            return {"status": "stopping"}
        raise ValueError("unsupported command")

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5)
            request = json.loads(raw)
            response = self._command(str(request.get("command") or ""), request.get("args") or {})
            writer.write((json.dumps(response) + "\n").encode()); await writer.drain()
        except (asyncio.TimeoutError, json.JSONDecodeError):
            writer.write(b'{"status":"error","error":"invalid request"}\n'); await writer.drain()
        except (InvalidTransition, SessionNotFound, ValueError) as exc:
            writer.write((json.dumps({"status": "error", "error": str(exc)}) + "\n").encode()); await writer.drain()
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


async def request(command: str, socket: Path | None = None, args: dict[str, Any] | None = None) -> dict[str, Any]:
    path = socket or socket_path()
    reader, writer = await asyncio.open_unix_connection(path)
    writer.write((json.dumps({"command": command, "args": args or {}}) + "\n").encode()); await writer.drain()
    result = json.loads(await reader.readline())
    writer.close(); await writer.wait_closed()
    return result


def run_daemon() -> None:
    asyncio.run(FlowDaemon().run())


if __name__ == "__main__":
    run_daemon()
