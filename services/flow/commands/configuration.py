"""Persistent privacy configuration for the local observer."""

from __future__ import annotations

from ..config import config_dir
from ..privacy import PrivacyPolicy

NAME = "config"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="configure local FLOW privacy")
    parser.add_argument("action", choices=["list", "exclude-app", "include-app"])
    parser.add_argument("application", nargs="?")


def _path():
    return config_dir() / "privacy.json"


def run(args) -> int:
    policy = PrivacyPolicy.load(_path())
    if args.action == "list":
        for item in sorted(policy.excluded_apps):
            print(item)
        return 0
    if not args.application or not args.application.strip():
        print(f"flow config: {args.action} requires an application name")
        return 2
    if args.action == "exclude-app":
        policy.add_exclusion(args.application)
    else:
        policy.remove_exclusion(args.application)
    policy.save(_path())
    print(f"FLOW privacy: {'excluded' if args.action == 'exclude-app' else 'included'} {args.application}")
    return 0
