"""``flow devices`` lists this account's devices; ``flow devices revoke ID`` signs one out remotely."""

from __future__ import annotations

from ..cloud.errors import CloudError, CloudRejected
from ..config import config_dir
from ..credentials import clear_account
from ..device import device_id
from ._common import ago, credential_store, error, make_client, run_client

NAME = "devices"


def add_parser(sub) -> None:
    parser = sub.add_parser("devices", help="list or revoke the devices signed in to your account")
    parser.add_argument("action", nargs="?", choices=["list", "revoke"], default="list")
    parser.add_argument("device_id", nargs="?")


def run(args) -> int:
    store = credential_store()
    if not store.load_bundle():
        error("not signed in. Run flow login.")
        return 1
    client = make_client(store)
    own = device_id(config_dir())
    try:
        if args.action == "revoke":
            if not args.device_id:
                error("devices revoke requires a device id (see `flow devices`)")
                return 2
            run_client(client, lambda c: c.revoke_device(args.device_id))
            print(f"Revoked {args.device_id}")
            if args.device_id == own:
                store.delete_token()
                clear_account(config_dir())
                print("That was this device; it is now signed out. Run flow login to sign in again.")
            return 0
        devices = run_client(client, lambda c: c.list_devices())
    except CloudRejected as exc:
        error(f"devices: {exc}")
        return 1
    except CloudError as exc:
        error(f"devices: {exc}")
        return 1
    if not devices:
        print("No devices.")
        return 0
    print(f"{'NAME':<24} {'OS':<14} {'STATE':<10} {'LAST SEEN':<10} ID")
    for item in devices:
        presence = (item.get("presence") or {}).get("state", "offline")
        state = "revoked" if item.get("revoked_at") else presence
        mark = "  (this device)" if item["id"] == own else ""
        print(f"{item.get('name', '')[:23]:<24} {item.get('os', '')[:13]:<14} {state:<10} "
              f"{ago(item.get('last_seen_at')):<10} {item['id']}{mark}")
    return 0
