"""``flow login``: browser-approved device authorization against the FLOW cloud."""

from __future__ import annotations

import sys

from ..auth import LoginError, device_login
from ..config import api_endpoint, config_dir
from ..credentials import CredentialStoreError, save_account
from ..device import device_id, device_name
from ..profiles import resolve_auth_mode
from ._common import credential_store, error, make_client, run_client

NAME = "login"


def add_parser(sub) -> None:
    parser = sub.add_parser("login", help="sign this device in to FLOW cloud")
    parser.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    parser.add_argument("--token", help="development shortcut (FLOW_AUTH_MODE=local only); use '-' to read it from stdin")


def run(args) -> int:
    try:
        mode = resolve_auth_mode()
    except ValueError as exc:
        error(f"login: {exc}")
        return 2
    store = credential_store()
    if args.token is not None:
        if mode != "local":
            error("login: --token is a local development shortcut and is refused unless FLOW_AUTH_MODE=local")
            return 2
        token = sys.stdin.readline().strip() if args.token == "-" else args.token.strip()
        if not token:
            error("login: empty token")
            return 2
        if args.token != "-":
            print("warning: a token on the command line is visible to other local users; prefer `--token -`", file=sys.stderr)
        try:
            store.save_bundle({"access_token": token, "user": {}, "device_id": device_id(config_dir()), "api_url": api_endpoint()})
            save_account(config_dir(), {"device_name": device_name(), "device_id": device_id(config_dir()),
                                        "api_url": api_endpoint()})
        except CredentialStoreError as exc:
            error(f"login: {exc}")
            return 1
        print("Logged in with a development token (local mode; no refresh token, so it will not renew).")
        return 0
    client = make_client(store)
    try:
        bundle = run_client(client, lambda c: device_login(c, store, config_dir(), open_browser=not args.no_browser))
    except LoginError as exc:
        error(f"login: {exc}")
        return 1
    except CredentialStoreError as exc:
        error(f"login: authorized, but the credentials could not be saved: {exc}")
        return 1
    except KeyboardInterrupt:
        error("login cancelled")
        return 130
    print("\n✓ Device authorized")
    print(f"Signed in as {bundle['user'].get('email') or 'unknown user'}")
    return 0
