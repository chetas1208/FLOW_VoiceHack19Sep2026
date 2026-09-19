"""CLI side of the local daemon IPC, plus the cloud command fallback.

Local-first: every command goes to the daemon over ``config_dir/flow.sock`` (JSON lines, see ``ipc_protocol``).
The cloud command API (``POST /v1/commands``, ``source=cli``) is used only when

* the daemon is not reachable and the user is signed in, or
* the daemon says the session is not one of its own (``not_found``) and the user is signed in
  (a session running on another of the user's devices).

Both paths issue the same ``SessionCommand`` types, so the web and the CLI cannot diverge. Nothing here reads
observation text: command arguments come from the user's argv or their explicit prompt answers.

IPC command arguments used by the CLI (all accept an optional ``session_id``)::

    session.start {goal, permission_policy}      session.stop|pause|resume|status {}     session.list {status?}
    task.add {instruction, permission_level?}    task.list {}   task.show {task_id}      task.cancel {task_id}
    approval.list {}                             approval.resolve {approval_id, approve: bool}
    recommend.get {}                             recommend.do {recommendation_id?}
    ask {question}                               goal.get {}    goal.set {goal}
    voice.mute {minutes?}   voice.unmute {}      subtasks.set {subtasks: [{id?, title, status}]}
    events.subscribe {after?}                    ping {}        status {}
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


# ---- cloud fallback ----------------------------------------------------------------------------------
def make_cloud():
    """A ``CloudClient`` when this device is signed in and cloud use is allowed, else ``None`` (patched in tests)."""
    if cloud_sync_disabled():
        return None
    from ..commands._common import credential_store, make_client
    store = credential_store()
    try:
        if not store.load_bundle():
            return None
    except Exception:  # noqa: BLE001 - a locked keychain reads as signed out
        return None
    return make_client(store)


def is_logged_in() -> bool:
    return make_cloud() is not None


def _run_cloud(coro_factory):
    from ..commands._common import run_client
    client = make_cloud()
    if client is None:
        raise CloudFallbackUnavailable(NOT_SIGNED_IN_HELP)
    from ..cloud.errors import CloudError, CloudRejected, CloudUnauthorized, CloudUnavailable
    try:
        return run_client(client, coro_factory)
    except CloudUnauthorized as exc:
        raise CloudFallbackUnavailable(str(exc)) from exc
    except CloudUnavailable as exc:
        raise CloudFallbackUnavailable(f"FLOW cloud is unreachable: {exc}") from exc
    except CloudRejected as exc:
        raise IpcError(str(exc), exc.code or "failed") from exc
    except CloudError as exc:
        raise IpcError(str(exc)) from exc


def _minutes(args: dict[str, Any]) -> dict[str, Any]:
    return {"minutes": int(args["minutes"])} if args.get("minutes") else {}


# ipc command -> (SessionCommand type, payload builder). ``approval.resolve`` picks its type from ``approve``.
CLOUD_WRITES: dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "session.stop": ("STOP", lambda a: {}),
    "session.pause": ("PAUSE", lambda a: {}),
    "session.resume": ("RESUME", lambda a: {}),
    "task.add": ("ADD_TASK", lambda a: {"instruction": a["instruction"],
                                        **({"permission_level": a["permission_level"]} if a.get("permission_level") else {})}),
    "task.cancel": ("CANCEL_TASK", lambda a: {"task_id": a["task_id"]}),
    "approval.resolve": ("APPROVE_ACTION", lambda a: {"approval_id": a["approval_id"]}),
    "recommend.do": ("EXECUTE_RECOMMENDATION", lambda a: {"recommendation_id": a.get("recommendation_id")}),
    "ask": ("ASK", lambda a: {"question": a["question"]}),
    "goal.set": ("UPDATE_GOAL", lambda a: {"goal": a["goal"]}),
    "voice.mute": ("MUTE_VOICE", _minutes),
    "voice.unmute": ("UNMUTE_VOICE", lambda a: {}),
    "subtasks.set": ("UPDATE_SUBTASKS", lambda a: {"subtasks": a["subtasks"]}),
}
CLOUD_READS = {"session.list", "session.status", "task.list", "task.show", "approval.list", "recommend.get", "goal.get"}
CLOUD_WAIT_SECONDS = {"ask": 45.0, "recommend.do": 20.0, "task.add": 20.0}
DEFAULT_CLOUD_WAIT = 15.0
POLL_INTERVAL = 0.6


def cloud_supports(command: str) -> bool:
    return command in CLOUD_WRITES or command in CLOUD_READS


def _entity_data(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(item.get("data") or item) for item in items]


def cloud_call(command: str, args: dict[str, Any] | None = None, *, wait: float | None = None) -> Any:
    """Run one IPC-shaped command through the cloud. Writes queue a ``SessionCommand`` and wait for its result."""
    args = dict(args or {})
    session_id = args.get("session_id")
    if command in CLOUD_READS:
        return _cloud_read(command, args, session_id)
    if command not in CLOUD_WRITES:
        raise CloudFallbackUnavailable(f"{command} is only available through the local daemon")
    if not session_id:
        raise IpcError("this needs a session id (see: flow sessions)", "bad_request")
    ctype, build = CLOUD_WRITES[command]
    if command == "approval.resolve" and args.get("approve") is False:
        ctype = "DENY_ACTION"
    if command == "recommend.do" and not args.get("recommendation_id"):
        pending = _cloud_read("recommend.get", args, session_id)
        rec = (pending or {}).get("recommendation") if isinstance(pending, dict) else None
        if not rec:
            raise IpcError("there is no pending recommendation for that session", NOT_FOUND)
        args["recommendation_id"] = rec["id"]
    payload = build(args)
    timeout = wait if wait is not None else CLOUD_WAIT_SECONDS.get(command, DEFAULT_CLOUD_WAIT)

    async def go(client):
        created = await client.create_command(ctype, session_id=session_id, payload=payload, source="cli",
                                              command_id=new_id("cmd"))
        deadline = time.monotonic() + timeout
        current = created
        while CommandStatus(current.get("status", "queued")) not in TERMINAL_COMMAND_STATUSES:
            if time.monotonic() >= deadline:
                break
            import asyncio
            await asyncio.sleep(POLL_INTERVAL)
            current = await client.get_command(created["command_id"])
        return current

    command_row = _run_cloud(go)
    status = command_row.get("status")
    result = command_row.get("result") or {}
    if status in {"failed", "denied", "expired", "cancelled"}:
        raise IpcError(str(result.get("error") or result.get("message") or f"command {status}"), status)
    return {**(result if isinstance(result, dict) else {}), "via": "cloud", "command_id": command_row.get("command_id"),
            "status": status, "session_id": session_id}


def _cloud_read(command: str, args: dict[str, Any], session_id: str | None) -> Any:
    if command == "session.list":
        async def go(client):
            return (await client.list_sessions(limit=100)).get("items", [])
        return {"sessions": _run_cloud(go), "via": "cloud"}
    if command == "approval.list":
        async def go(client):
            return (await client._request("GET", "/v1/approvals", params={"status": "pending"})).get("items", [])
        return {"approvals": _entity_data(_run_cloud(go)), "via": "cloud"}
    if not session_id:
        raise IpcError("this needs a session id (see: flow sessions)", "bad_request")
    if command in {"session.status", "goal.get"}:
        async def go(client):
            return await client._request("GET", f"/v1/sessions/{session_id}/live")
        live = _run_cloud(go)
        return {"goal": live.get("goal"), "via": "cloud"} if command == "goal.get" else {**live, "via": "cloud"}
    kind = "recommendation" if command == "recommend.get" else "task"
    params: dict[str, Any] = {"kind": kind, "limit": 100}
    if command == "recommend.get":
        params["status"] = "pending"

    async def go(client):
        return (await client._request("GET", f"/v1/sessions/{session_id}/entities", params=params)).get("items", [])
    items = _entity_data(_run_cloud(go))
    if command == "recommend.get":
        best = max(items, key=lambda r: float(r.get("confidence") or 0), default=None)
        return {"recommendation": best, "via": "cloud"}
    if command == "task.show":
        found = next((t for t in items if t.get("id") == args.get("task_id")), None)
        if found is None:
            raise IpcError(f"task not found: {args.get('task_id')}", NOT_FOUND)
        return {"task": found, "via": "cloud"}
    return {"tasks": items, "via": "cloud"}


def cloud_events(session_id: str, after: int = 0, interval: float = 1.5) -> Iterator[tuple[str, dict[str, Any]]]:
    """Poll the cloud event log (``GET /v1/sessions/{id}/events``) so ``flow attach`` works on a remote session."""
    last = after
    while True:
        async def go(client, cursor=last):
            return await client._request("GET", f"/v1/sessions/{session_id}/events",
                                         params={"after": cursor, "limit": 100})
        page = _run_cloud(go)
        for item in sorted(page.get("items", []), key=lambda e: e.get("sequence", 0)):
            last = max(last, item.get("sequence", 0))
            yield "event", item
        if not page.get("items"):
            _sleep(interval)


# ---- routing -----------------------------------------------------------------------------------------
def dispatch(command: str, args: dict[str, Any] | None = None, *, session_id: str | None = None) -> Any:
    """Send ``command`` to the local daemon; fall back to the cloud when that is the only way to reach it."""
    payload = dict(args or {})
    if session_id:
        payload["session_id"] = session_id
    try:
        return call(command, payload)
    except DaemonUnavailable as unavailable:
        if not cloud_supports(command) or command == "session.list":
            raise
        try:
            return cloud_call(command, payload)
        except CloudFallbackUnavailable as reason:
            raise DaemonUnavailable(f"{unavailable}\n{reason}") from reason
    except IpcError as exc:
        if exc.code == NOT_FOUND and session_id and cloud_supports(command) and is_logged_in():
            return cloud_call(command, payload)
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
        notes.append("FLOW daemon is not running (start it with: flow daemon start); showing cloud sessions only.")
    except IpcError as exc:
        notes.append(f"local sessions unavailable: {exc}")
    try:
        for item in _rows(cloud_call("session.list", {}), "sessions"):
            merged = rows.get(item["id"])
            if merged is None:
                item["where"] = "cloud"
                rows[item["id"]] = item
            else:
                for key in ("device_name", "device_id"):
                    merged.setdefault(key, item.get(key))
    except CloudFallbackUnavailable as exc:
        if is_logged_in():
            notes.append(str(exc))
    except IpcError as exc:
        notes.append(f"cloud sessions unavailable: {exc}")
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
