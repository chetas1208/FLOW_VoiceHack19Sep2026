"""``flow logout``: revoke the refresh token (best effort), clear the keychain, keep local history."""

from __future__ import annotations

import asyncio

from ..cloud.client import CloudClient
from ..config import config_dir
from ..credentials import clear_account
from ._common import credential_store

NAME = "logout"


def add_parser(sub) -> None:
    sub.add_parser("logout", help="sign out and remove stored credentials (local history is kept)")


async def _remote_logout(bundle: dict) -> None:
    client = CloudClient(credential_store(), endpoint=bundle["api_url"], retries=0, timeout=5.0)
    try:
        await client.logout(bundle["refresh_token"])
    finally:
        await client.aclose()


def run(args) -> int:
    store = credential_store()
    bundle = store.load_bundle()
    revoked = False
    if bundle and bundle.get("refresh_token") and bundle.get("api_url") and not bundle.get("refresh_invalid"):
        try:
            asyncio.run(_remote_logout(bundle))
            revoked = True
        except Exception:  # noqa: BLE001 - best effort: being offline must not stop a local sign-out
            pass
    store.delete_token()
    clear_account(config_dir())
    if bundle is None:
        print("Not signed in. Nothing to do.")
    else:
        print("Signed out." + ("" if revoked else " (Could not reach FLOW to revoke the token; it will expire on its own.)"))
        print("Local session history was kept.")
    return 0
