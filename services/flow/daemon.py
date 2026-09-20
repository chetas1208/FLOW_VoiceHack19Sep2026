"""Minimal authenticated-by-filesystem local daemon IPC."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import platform
import signal
from pathlib import Path
from typing import Any

from .config import config_dir
from .remote.ipc_protocol import (BAD_REQUEST, FAILED, FORBIDDEN_PEER, UNAUTHENTICATED, encode,
                                  error, load_or_create_token, ok, parse_request, peer_allowed, token_matches)
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
        # Unit tests use an explicit temporary socket and the legacy helper;
        # the installed daemon always uses authenticated IPC.
        self.secure = self.socket.resolve() == socket_path().resolve()
        self.token: str | None = None
        self.runtime = None
        self.runtime_task: asyncio.Task[Any] | None = None

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
                    "session": session.to_dict() if session else None,
                    "runtime": self.runtime.report().get("runtime") if self.runtime else
                    {"observer": "not_configured" if platform.system() != "Darwin" else "not_started"}}
        if command == "session.start":
            goal = str(args.get("goal") or "").strip()
            if not goal:
                raise ValueError("session.start requires a goal")
            if self.session_id:
                raise ValueError("a FLOW session is already active")
            session = self.manager.start_session(goal, metadata={"daemon_pid": os.getpid()})
            self.session_id = session.id
            self._start_runtime(session.id)
            from .account.heartbeat_sync import push_heartbeat
            push_heartbeat(self)
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
                if self.runtime:
                    self.runtime.stop()
                self.session_id = None
            from .account.heartbeat_sync import push_heartbeat
            push_heartbeat(self)
            return {"session": session.to_dict()}
        if command == "session.list":
            return {"sessions": [session.to_dict() for session in self.manager.list_sessions()]}
        if command == "shutdown":
            if self.server:
                self.server.close()
            return {"status": "stopping"}
        raise ValueError("unsupported command")

    def _start_runtime(self, session_id: str) -> None:
        """Start real observation only when the host has the required capabilities."""
        if platform.system() != "Darwin":
            return
        from .intelligence import QwenVLIntelligenceEngine
        from .observer import create_observer
        from .runtime import SessionRuntime
        observer = create_observer()
        intelligence = QwenVLIntelligenceEngine()
        self.runtime = SessionRuntime(self.manager, session_id, observer, intelligence)
        self.runtime_task = asyncio.create_task(self.runtime.run(), name=f"flow-runtime-{session_id}")

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=5)
            if self.secure:
                sock = writer.get_extra_info("socket")
                if not peer_allowed(sock):
                    writer.write(encode(error("peer credentials rejected", FORBIDDEN_PEER)))
                    await writer.drain()
                    return
                presented, command, args = parse_request(raw)
                if not self.token or not token_matches(self.token, presented):
                    writer.write(encode(error("invalid daemon token", UNAUTHENTICATED)))
                    await writer.drain()
                    return
                writer.write(encode(ok(self._command(command, args))))
                await writer.drain()
            else:
                request = json.loads(raw)
                response = self._command(str(request.get("command") or ""), request.get("args") or {})
                writer.write((json.dumps(response) + "\n").encode()); await writer.drain()
        except (asyncio.TimeoutError, json.JSONDecodeError):
            writer.write(encode(error("invalid request", BAD_REQUEST)) if self.secure
                         else b'{"status":"error","error":"invalid request"}\n'); await writer.drain()
        except (InvalidTransition, SessionNotFound, ValueError) as exc:
            writer.write(encode(error(str(exc), FAILED)) if self.secure else
                         (json.dumps({"status": "error", "error": str(exc)}) + "\n").encode()); await writer.drain()
        finally:
            writer.close(); await writer.wait_closed()

    async def run(self) -> None:
        self.socket.parent.mkdir(parents=True, exist_ok=True)
        self.socket.unlink(missing_ok=True)
        if self.secure:
            self.token = load_or_create_token(self.socket.parent)
        self.server = await asyncio.start_unix_server(self.handle, path=self.socket)
        self.socket.chmod(0o600)
        self.pid.write_text(str(os.getpid())); self.pid.chmod(0o600)
        from .account.heartbeat_sync import heartbeat_loop, push_heartbeat
        push_heartbeat(self)
        pulse = asyncio.create_task(heartbeat_loop(self), name="flow-account-heartbeat")
        try:
            async with self.server:
                await self.server.serve_forever()
        finally:
            pulse.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pulse
            self.socket.unlink(missing_ok=True)
            self.pid.unlink(missing_ok=True)


async def request(command: str, socket: Path | None = None, args: dict[str, Any] | None = None) -> dict[str, Any]:
    path = socket or socket_path()
    reader, writer = await asyncio.open_unix_connection(path)
    writer.write((json.dumps({"command": command, "args": args or {}}) + "\n").encode()); await writer.drain()
    result = json.loads(await reader.readline())
    writer.close(); await writer.wait_closed()
    return result.get("result", result) if result.get("ok") else result


def run_daemon() -> None:
    asyncio.run(FlowDaemon().run())


if __name__ == "__main__":
    run_daemon()
