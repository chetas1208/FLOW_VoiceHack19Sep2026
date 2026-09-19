"""First-run local setup; never downloads multi-gigabyte models implicitly."""

from __future__ import annotations

import platform

from ..config import config_dir, data_dir
from ..device import device_id
from ..models_registry import ModelManager
from ..privacy import PrivacyPolicy

NAME = "setup"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="initialize FLOW local storage and report setup requirements")
    parser.add_argument("--install-models", action="store_true", help="download the two default local models")


def run(args) -> int:
    config_dir().mkdir(parents=True, exist_ok=True)
    data_dir().mkdir(parents=True, exist_ok=True)
    device_id(config_dir())
    privacy = config_dir() / "privacy.json"
    if not privacy.exists():
        PrivacyPolicy().save(privacy)
    manager = ModelManager()
    if args.install_models:
        try:
            manager.install()
        except (RuntimeError, OSError) as exc:
            print(f"FLOW setup: model installation failed: {exc}")
            return 2
    statuses = manager.status()
    print("FLOW SETUP\n")
    print(f"Config       {config_dir()}")
    print(f"Data         {data_dir()}")
    print(f"Platform     {platform.platform()}")
    for item in statuses:
        print(f"{item['name']:<24} {item['status']}")
    if any(item["status"] != "ready" for item in statuses):
        print("\nRun `flow models install` when local model downloads are desired.")
    return 0
