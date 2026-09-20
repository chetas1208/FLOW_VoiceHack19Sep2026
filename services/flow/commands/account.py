"""FLOW account and device commands; session contents remain local."""

from __future__ import annotations

import os
import webbrowser

from ..account.client import AccountClient, AccountClientError
from ..config import web_endpoint
from ..credentials import default_secret_store

NAMES = ("login", "logout", "whoami", "account", "devices")


def add_parser(subparsers) -> None:
    login = subparsers.add_parser("login", help="sign in and authorize this device in a browser")
    login.add_argument("--server", default=os.getenv("FLOW_ACCOUNT_URL", web_endpoint()))
    login.add_argument("--no-browser", action="store_true")
    login.add_argument("--timeout", type=float, default=300, help="seconds to wait for browser approval")
    for name in NAMES[1:]:
        subparsers.add_parser(name, help="show FLOW account/device state" if name != "logout" else "sign out")


def run(args) -> int:
    client = AccountClient(getattr(args, "server", None), secrets=default_secret_store())
    try:
        if args.command == "login":
            request, request_id, url = client.start_login()
            if not args.no_browser:
                webbrowser.open(url)
            code = f"\nVerification code: {client.user_code}" if client.user_code else ""
            print(f"Open this URL to authorize FLOW:\n{url}{code}\nRequest state: {request.state}")
            client.wait_for_approval(request_id, request, timeout=args.timeout)
            client.heartbeat({"daemon": "not_running", "agent": "idle", "model": "not_loaded"})
            print("FLOW device authorized and linked to your account")
            return 0
        if args.command == "logout":
            client.logout()
            print("FLOW signed out")
            return 0
        result = client.devices() if args.command == "devices" else client.whoami()
        print(result)
        return 0
    except AccountClientError as exc:
        print(f"flow {args.command}: {exc}")
        return 2
