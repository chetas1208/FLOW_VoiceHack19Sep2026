"""CLI side of the local daemon IPC.

The daemon on the user's Mac is the only backend: every command goes to it over ``config_dir/flow.sock`` (JSON
lines, see ``ipc_protocol``); remote/web clients reach the same handlers through the daemon's HTTP API, so the CLI
and the web cannot diverge (both end in the same ``SessionCommand``). Nothing here reads observation text: command
arguments come from the user's argv or their explicit prompt answers.

IPC command arguments used by the CLI (all session-scoped commands accept an optional ``session_id``)::

    session.start {goal, permission_policy}      session.stop|pause|resume|status {}     session.list {}
    task.add {instruction, permission_level?}    task.list {}   task.show {task_id}      task.cancel {task_id}
    task.rollback {task_id}
    approval.list {}                             approval.resolve {approval_id, approve: bool}
    recommend.get {}                             recommend.do {recommendation_id}
    ask {question}                               goal.get {}    goal.set {goal}         goal.confirm {}
    voice.mute {minutes?}   voice.unmute {}      voice.on {}    voice.off {}
    subtasks.set {subtasks: [{id?, title, status}]}
    permissions.allow_write {}                   permissions.set_policy {policy}
    remote.status {}  remote.enable {public}  remote.disable {}  remote.pair {public}  remote.clients {}
    remote.revoke {client_id}
    events.subscribe {session_id, replay?}       ping {}        status {}
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator

from ..config import cloud_sync_disabled, config_dir, web_endpoint
from ..remote_models import TERMINAL_COMMAND_STATUSES, CommandStatus, new_id
from .ipc_protocol import MAX_LINE_BYTES, NOT_FOUND, UNAUTHENTICATED, IpcError, encode, read_token

COMMANDS = ("ping", "status", "session.start", "session.stop", "session.pause", "session.resume", "session.list",
            "session.status", "task.add", "task.list", "task.show", "task.cancel", "approval.list", "approval.resolve",
            "recommend.get", "recommend.do", "ask", "goal.get", "goal.set", "voice.mute", "voice.unmute", "subtasks.set",
            "events.subscribe")
DAEMON_DOWN_HELP = "FLOW daemon is not running. Start it with: flow daemon start"
NOT_SIGNED_IN_HELP = "Not signed in, so the cloud cannot be used either. Run flow login to control sessions remotely."
NON_TERMINAL_HIDDEN = {"completed", "failed"}

_sleep: Callable[[float], None] = time.sleep


class DaemonUnavailable(RuntimeError):
    """The daemon socket is missing or refusing connections."""


class CloudFallbackUnavailable(RuntimeError):
    """The command could not go to the cloud (signed out, sync disabled, or not expressible as a command)."""


def socket_path() -> Path:
    return config_dir() / "flow.sock"


# ---- local daemon ------------------------------------------------------------------------------------
def _open(path: Path, timeout: float | None) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(path))
    except (FileNotFoundError, ConnectionRefusedError, NotADirectoryError, PermissionError, socket.timeout) as exc:
        sock.close()
        raise DaemonUnavailable(DAEMON_DOWN_HELP) from exc
    except OSError as exc:
        sock.close()
        raise DaemonUnavailable(f"{DAEMON_DOWN_HELP} ({exc.strerror or exc})") from exc
    return sock


def _send(sock: socket.socket, command: str, args: dict[str, Any] | None, token: str | None, directory: Path) -> None:
    secret = token if token is not None else (read_token(directory) or "")
    sock.sendall(encode({"token": secret, "command": command, "args": args or {}}))


def _lines(sock: socket.socket) -> Iterator[dict[str, Any]]:
    buffer = b""
    while True:
        while b"\n" not in buffer:
            if len(buffer) > MAX_LINE_BYTES:
                raise IpcError("daemon sent an oversized line")
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                raise DaemonUnavailable("FLOW daemon did not answer in time") from None
            if not chunk:
                if buffer.strip():
                    break
                return
            buffer += chunk
        line, _, buffer = buffer.partition(b"\n")
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except ValueError as exc:
            raise IpcError("daemon sent an invalid response") from exc


def _raise_for(response: dict[str, Any]) -> Any:
    if response.get("ok"):
        return response.get("result")
    message, code = str(response.get("error") or "command failed"), response.get("code") or "failed"
    if code == UNAUTHENTICATED:
        message = ("the daemon rejected this CLI (ipc token mismatch). Restart it with: flow daemon stop && flow daemon start")
    raise IpcError(message, code)


def call(command: str, args: dict[str, Any] | None = None, *, timeout: float = 15.0, socket_file: Path | None = None,
         token: str | None = None) -> Any:
    """One request/response round trip. Returns ``result``; raises ``DaemonUnavailable`` or ``IpcError``."""
    path = socket_file or socket_path()
    sock = _open(path, timeout)
    try:
        _send(sock, command, args, token, path.parent)
        for response in _lines(sock):
            return _raise_for(response)
        raise DaemonUnavailable("FLOW daemon closed the connection without answering")
    finally:
        sock.close()


def stream(command: str, args: dict[str, Any] | None = None, *, socket_file: Path | None = None,
           token: str | None = None, timeout: float | None = None) -> Iterator[tuple[str, dict[str, Any]]]:
    """Generator for ``events.subscribe``: yields ``("event"|"notice", payload)`` until the daemon closes.

    The first response line is the subscription acknowledgement (raised as ``IpcError`` if refused). The socket
    is always closed when the generator is closed or interrupted (``KeyboardInterrupt`` propagates to the caller).
    """
    path = socket_file or socket_path()
    sock = _open(path, timeout)
    try:
        _send(sock, command, args, token, path.parent)
        acknowledged = False
        for message in _lines(sock):
            if not acknowledged:
                acknowledged = True
                if "ok" in message:
                    _raise_for(message)
                    continue
            if isinstance(message.get("event"), dict):
                yield "event", message["event"]
            elif isinstance(message.get("notice"), dict):
                yield "notice", message["notice"]
            elif message.get("ok") is False:
                _raise_for(message)
    finally:
        sock.close()


def daemon_running(timeout: float = 1.0) -> bool:
    try:
        call("ping", timeout=timeout)
        return True
    except (DaemonUnavailable, IpcError):
        return False


def spawn_daemon() -> None:
    subprocess.Popen([sys.executable, "-m", "services.flow.daemon"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                     env={**os.environ})


def ensure_daemon(wait: float = 8.0, spawn: Callable[[], None] | None = None) -> None:
    """Return once the daemon answers ``ping``, starting it if needed. Raises ``DaemonUnavailable`` on failure."""
    if daemon_running():
        return
    try:
        (spawn or spawn_daemon)()
    except OSError as exc:
        raise DaemonUnavailable(f"could not start the FLOW daemon: {exc}") from exc
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if daemon_running():
            return
        _sleep(0.2)
    raise DaemonUnavailable("the FLOW daemon did not become ready. Check it with: flow daemon status")


# ---- routing -----------------------------------------------------------------------------------------
def dispatch(command: str, args: dict[str, Any] | None = None, *, session_id: str | None = None) -> Any:
    """Send a command to the local daemon.

    Cloud synchronization is intentionally not a hidden fallback: this client
    only operates on the daemon that owns the local session.
    """
    payload = dict(args or {})
    if session_id:
        payload["session_id"] = session_id
    try:
        return call(command, payload)
    except DaemonUnavailable:
        raise


def _rows(result: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        result = result.get(key) or result.get("items") or []
    return [dict(item) for item in result or [] if isinstance(item, dict)]


def _row_data(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("data") if isinstance(item.get("data"), dict) else item


def list_sessions(include_finished: bool = False) -> tuple[list[dict[str, Any]], list[str]]:
    """Local and cloud sessions merged by id -> (rows, notes). Local rows win; rows say which device they run on."""
    from ..config import config_dir as _cfg
    from ..device import device_id, device_name
    notes: list[str] = []
    rows: dict[str, dict[str, Any]] = {}
    try:
        for item in _rows(call("session.list", {}), "sessions"):
            item.setdefault("device_name", device_name())
            item["device_id"] = item.get("device_id") or device_id(_cfg())
            item["where"] = "local"
            rows[item["id"]] = item
    except DaemonUnavailable:
        notes.append("FLOW daemon is not running (start it with: flow daemon start).")
    except IpcError as exc:
        notes.append(f"local sessions unavailable: {exc}")
    out = [r for r in rows.values() if include_finished or str(r.get("status")) not in NON_TERMINAL_HIDDEN]
    out.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    return out, notes


def resolve_session(explicit: str | None, prefer: tuple[str, ...] | None = None) -> str:
    """The session a command acts on: the explicit id, else the only live session (preferring ``prefer`` statuses)."""
    if explicit:
        return explicit
    rows, _ = list_sessions()
    if prefer:
        wanted = [r for r in rows if str(r.get("status")) in prefer]
        rows = wanted or rows
    if len(rows) == 1:
        return rows[0]["id"]
    if not rows:
        raise IpcError("no active session. Start one with: flow start \"your goal\"", NOT_FOUND)
    listing = ", ".join(r["id"] for r in rows[:5])
    raise IpcError(f"more than one session is live ({listing}). Pass --session ID (see: flow sessions)", "bad_request")


def remote_url(session_id: str) -> str:
    return f"{web_endpoint()}/session/{session_id}"


def guarded(func: Callable[[], int]) -> int:
    """Run a command body and turn the expected failures into friendly stderr messages and exit codes."""
    try:
        return func()
    except DaemonUnavailable as exc:
        print(f"flow: {exc}", file=sys.stderr)
        return 3
    except CloudFallbackUnavailable as exc:
        print(f"flow: {exc}", file=sys.stderr)
        return 3
    except IpcError as exc:
        print(f"flow: {exc}", file=sys.stderr)
        return 1 if exc.code in {NOT_FOUND, "denied", "failed"} else 2
    except ValueError as exc:
        print(f"flow: {exc}", file=sys.stderr)
        return 2
