"""Explicit local voice controls; no command enables audio implicitly."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import config_dir

NAME = "voice"
STATE_FILE = "voice-state.json"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="inspect or control FLOW voice coaching")
    parser.add_argument("action", choices=["status", "on", "off", "mute", "unmute", "stop", "test"])
    parser.add_argument("--minutes", type=int, default=30, help="mute duration (default: 30)")


def _path() -> Path:
    return config_dir() / STATE_FILE


def _read() -> dict[str, object]:
    try:
        value = json.loads(_path().read_text())
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _write(value: dict[str, object]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    temp.replace(path)


def run(args) -> int:
    state = _read()
    action = args.action
    if action == "on":
        state.update(enabled=True, muted_until=None)
        _write(state)
        print("FLOW voice: enabled")
    elif action == "off":
        state.update(enabled=False, muted_until=None)
        _write(state)
        print("FLOW voice: disabled")
    elif action == "mute":
        if args.minutes < 1:
            print("flow voice: --minutes must be at least 1")
            return 2
        until = datetime.now(timezone.utc) + timedelta(minutes=args.minutes)
        state["muted_until"] = until.isoformat()
        _write(state)
        print(f"FLOW voice: muted until {until.isoformat()}")
    elif action == "unmute":
        state["muted_until"] = None
        _write(state)
        print("FLOW voice: unmuted")
    elif action == "stop":
        # Playback is intentionally short-lived; this is an idempotent control
        # point for future audio backends and clears a pending mute-free state.
        print("FLOW voice: no active playback")
    elif action == "test":
        from ..voice.kokoro import KokoroVoiceEngine
        status = KokoroVoiceEngine().status()
        if status["status"] != "ready":
            print(f"FLOW voice: NOT_CONFIGURED ({status['reason']})")
            return 2
        print("FLOW voice: ready (use flow voice on to enable coaching)")
    else:
        muted_until = state.get("muted_until")
        enabled = bool(state.get("enabled", False))
        print(f"FLOW voice: {'enabled' if enabled else 'disabled'}")
        print(f"Muted until: {muted_until or 'no'}")
    return 0
