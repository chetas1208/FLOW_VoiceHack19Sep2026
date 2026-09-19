"""``flow whoami``: which account and device this machine is signed in as."""

from __future__ import annotations

from ..cloud.errors import CloudError, CloudUnauthorized, CloudUnavailable
from ..config import api_endpoint, config_dir
from ..credentials import load_account
from ..device import device_id, device_name
from ..sync.state import read_sync_status
from ._common import ago, cloud_state_line, credential_store, existing_flow_store, make_client, run_client

NAME = "whoami"


def add_parser(sub) -> None:
    parser = sub.add_parser("whoami", help="show the signed-in user, device and sync state")
    parser.add_argument("--online", action="store_true", help="verify the credentials with the cloud")


def run(args) -> int:
    store = credential_store()
    bundle = store.load_bundle()
    if not bundle or not bundle.get("access_token"):
        print("Not signed in. Run flow login.")
        return 1
    account = load_account(config_dir())
    user = bundle.get("user") or {}
    print(f"User        {user.get('email') or account.get('email') or 'unknown (development token)'}")
    print(f"Device      {account.get('device_name') or device_name()}")
    print(f"Device ID   {bundle.get('device_id') or device_id(config_dir())}")
    print(f"Cloud       {bundle.get('api_url') or api_endpoint()}")
    flow_store = existing_flow_store()
    if flow_store is not None:
        status = read_sync_status(flow_store, store)
        extra = f", {status['pending']} pending" if status["pending"] else ""
        print(f"Sync        {cloud_state_line(status)}{extra}")
    else:
        print("Sync        no local sessions yet")
    if args.online:
        try:
            me = run_client(make_client(store, retries=1), lambda c: c.whoami())
            print(f"Verified    ✓ cloud accepted these credentials ({me.get('principal', 'device')})")
        except CloudUnauthorized as exc:
            print(f"Verified    ✗ {exc}")
            return 1
        except CloudUnavailable as exc:
            print(f"Verified    ? cloud unreachable ({exc})")
            return 1
        except CloudError as exc:
            print(f"Verified    ✗ {exc}")
            return 1
    return 0
