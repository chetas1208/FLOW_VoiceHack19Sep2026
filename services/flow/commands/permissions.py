"""Permission status command; only Screen Recording is required by FLOW."""

from __future__ import annotations

import platform

NAME = "permissions"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="show FLOW operating-system permissions")
    parser.add_argument("action", nargs="?", choices=["status", "request"], default="status")


def run(args) -> int:
    if platform.system() != "Darwin":
        print("FLOW PERMISSIONS\n\nScreen Recording       Not configured (requires macOS)")
        return 2
    from ..observer.macos.permissions import request_screen_recording, screen_recording_status
    status = request_screen_recording() if args.action == "request" else screen_recording_status()
    print(f"FLOW PERMISSIONS\n\nScreen Recording       {status.screen_recording.title()}\nSource                 {status.source}")
    return 0 if status.screen_recording == "granted" else 1
