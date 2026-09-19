"""Local daemon IPC protocol: JSON lines over a 0600 unix socket, authenticated twice.

Request (one JSON object per line)::

    {"token": "<contents of config_dir/ipc.token>", "command": "session.start", "args": {...}}

Response::

    {"ok": true, "result": {...}}   or   {"ok": false, "error": "...", "code": "..."}

``events.subscribe`` answers with a *stream*: the first line is ``{"ok": true, "result": {"subscribed": ...}}``
and every following line is ``{"event": {...}}`` (a persisted event with ``sequence``) or
``{"notice": {...}}`` (e.g. a pending approval) until the client disconnects.

Authentication (both must pass, otherwise the request is rejected and nothing is executed):

1. the caller's uid, taken from the kernel (``SO_PEERCRED`` on Linux, ``LOCAL_PEERCRED`` on macOS), equals the
   daemon's uid - the socket is 0600 as well, this closes the window where a file mode is changed or the fd is inherited;
2. the per-install random token in ``ipc.token`` (0600) - a same-uid process that cannot read the file cannot use IPC.
"""

from __future__ import annotations

import hmac
import json
import os
import platform
import secrets
import socket
import struct
import tempfile
from pathlib import Path
from typing import Any

TOKEN_FILE = "ipc.token"
MAX_LINE_BYTES = 1_048_576
SOL_LOCAL, LOCAL_PEERCRED = 0, 1  # macOS <sys/un.h>

# Stable error codes returned to clients.
UNAUTHENTICATED = "unauthenticated"
FORBIDDEN_PEER = "forbidden_peer"
BAD_REQUEST = "bad_request"
UNKNOWN_COMMAND = "unknown_command"
FAILED = "failed"
DENIED = "denied"
NOT_FOUND = "not_found"


class IpcError(Exception):
    """A command failed; ``code`` is machine readable, ``str(exc)`` is safe to show to the user."""

    def __init__(self, message: str, code: str = FAILED) -> None:
        super().__init__(message)
        self.code = code


def token_path(directory: Path) -> Path:
    return Path(directory) / TOKEN_FILE


def load_or_create_token(directory: Path) -> str:
    """Return the install token, creating it atomically with mode 0600 on first use (race-free)."""
    path = token_path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        return _read_token(path)
    except FileNotFoundError:
        pass
    value = secrets.token_urlsafe(32)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ipc.token.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(value)
        try:
            os.link(tmp, path)  # first writer wins so the CLI and the daemon never disagree
        except FileExistsError:
            pass
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return _read_token(path)


def _read_token(path: Path) -> str:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise PermissionError(f"{path} must not be accessible by group/others (mode {oct(mode)})")
    value = path.read_text().strip()
    if not value:
        raise FileNotFoundError(path)
    return value


def read_token(directory: Path) -> str | None:
    """Client side: the token if this user can read it, else None (never creates one)."""
    try:
        return _read_token(token_path(directory))
    except (FileNotFoundError, PermissionError, OSError):
        return None


def token_matches(expected: str, presented: Any) -> bool:
    return isinstance(presented, str) and bool(expected) and hmac.compare_digest(expected.encode(), presented.encode())


def peer_uid(sock: socket.socket) -> int | None:
    """The connecting process's effective uid according to the kernel, or None if it cannot be determined."""
    try:
        if platform.system() == "Darwin":
            data = sock.getsockopt(SOL_LOCAL, LOCAL_PEERCRED, 76)  # struct xucred
            _version, uid = struct.unpack_from("=II", data)
            return int(uid)
        data = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", data)
        return int(uid)
    except (OSError, AttributeError, struct.error):
        return None


def peer_allowed(sock: socket.socket | None, own_uid: int | None = None) -> bool:
    """Fail closed: an undeterminable peer is refused."""
    if sock is None:
        return False
    uid = peer_uid(sock)
    return uid is not None and uid == (os.getuid() if own_uid is None else own_uid)


def encode(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, separators=(",", ":"), default=str) + "\n").encode()


def parse_request(raw: bytes) -> tuple[str, str, dict[str, Any]]:
    """-> (token, command, args); raises IpcError(BAD_REQUEST)."""
    try:
        request = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise IpcError("invalid JSON request", BAD_REQUEST) from exc
    if not isinstance(request, dict):
        raise IpcError("request must be a JSON object", BAD_REQUEST)
    command, args = request.get("command"), request.get("args", {})
    if not isinstance(command, str) or not command or len(command) > 64:
        raise IpcError("missing command", BAD_REQUEST)
    if args is None:
        args = {}
    if not isinstance(args, dict):
        raise IpcError("args must be an object", BAD_REQUEST)
    return request.get("token") if isinstance(request.get("token"), str) else "", command, args


def ok(result: Any) -> dict[str, Any]:
    return {"ok": True, "result": result}


def error(message: str, code: str = FAILED) -> dict[str, Any]:
    return {"ok": False, "error": message, "code": code}


# ---- minimal async client (the CLI plug-ins may use their own; this one is what the tests use) --------------
async def call(socket_path: Path, command: str, args: dict[str, Any] | None = None, *, token: str | None = None,
               timeout: float = 30.0) -> dict[str, Any]:
    """One request/response round trip; returns the raw response object (``ok`` may be false)."""
    import asyncio
    if token is None:
        token = read_token(Path(socket_path).parent) or ""
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(socket_path), limit=MAX_LINE_BYTES), timeout)
    try:
        writer.write(encode({"token": token, "command": command, "args": args or {}}))
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout)
        if not line:
            return error("daemon closed the connection", UNAUTHENTICATED)
        return json.loads(line)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
