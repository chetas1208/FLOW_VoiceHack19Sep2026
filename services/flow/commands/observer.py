"""``flow observer``: real permission/context/display/capture checks for the macOS observer."""

from __future__ import annotations

import json
import platform
import sys

NAME = "observer"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser("observer", help="check the desktop observer")
    parser.add_argument("action", nargs="?", default="test", choices=["test", "permissions", "displays"])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--request", action="store_true", help="permissions: trigger the macOS consent prompt")
    parser.add_argument("--open", action="store_true", help="permissions: open System Settings")


def _emit(args, payload: dict, lines: list[str]) -> None:
    print(json.dumps(payload, indent=2) if args.json else "\n".join(lines))


def run(args) -> int:
    if platform.system() != "Darwin":
        _emit(args, {"status": "not_configured", "reason": "ScreenCaptureKit requires macOS"},
              ["FLOW observer: NOT_CONFIGURED (ScreenCaptureKit requires macOS)"])
        return 2
    from ..observer.macos.permissions import (open_screen_recording_settings, request_screen_recording,
                                              screen_recording_status)
    if args.action == "permissions":
        if args.open:
            open_screen_recording_settings()
        status = request_screen_recording() if args.request else screen_recording_status()
        _emit(args, {"status": "verified" if status.screen_recording == "granted" else "failed",
                     "screen_recording": status.screen_recording, "source": status.source},
              [f"Screen Recording   {status.screen_recording} (via {status.source})"])
        return 0 if status.screen_recording == "granted" else 1
    if args.action == "displays":
        from ..observer.macos.displays import list_displays
        try:
            items = [item.to_dict() for item in list_displays()]
        except Exception as exc:
            print(f"flow observer displays: {exc}", file=sys.stderr)
            return 1
        _emit(args, {"status": "verified", "displays": items},
              [f"Display {item['id']}  {item['width']:.0f}x{item['height']:.0f}  scale {item['scale']}"
               f"{'  main' if item['is_main'] else ''}" for item in items])
        return 0
    from ..validation.context import ValidationContext
    from ..validation.probes import check_screen_capture
    result = check_screen_capture(ValidationContext())
    lines = [f"FLOW OBSERVER TEST\n\nStatus            {result['status']}",
             f"Backend           {result.get('backend')}", f"Capture latency   {result.get('latency_ms')} ms",
             f"Displays          {len(result.get('displays', []))}"]
    if result.get("error"):
        lines.append(f"Error             {result['error']['message']}")
        if result["error"].get("hint"):
            lines.append(f"Hint              {result['error']['hint']}")
    _emit(args, result, lines)
    return {"verified": 0, "not_configured": 2}.get(result["status"], 1)
