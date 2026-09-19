"""FLOW command tree. Commands live in ``services/flow/commands/*`` and are auto-registered (see that package).

Only ``version`` and ``models`` are still handled inline here.
"""

from __future__ import annotations

import argparse
import sys

from .config import FLOW_VERSION
from .models_registry import MODEL_REGISTRY, ModelManager

VERSION = FLOW_VERSION


def _plugins():
    from .commands import discover
    return discover()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flow", description="FLOW local work-session observer and coach")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version")
    models = sub.add_parser("models")
    models.add_argument("action", choices=["status", "install", "remove"])
    models.add_argument("target", nargs="?", choices=["intelligence", "vision", "voice"])
    models.add_argument("--variant", choices=["4b", "2b"], help="explicit Qwen intelligence size")
    seen: dict[int, object] = {}
    for module in _plugins().values():
        if id(module) not in seen:  # a module with several NAMES registers all of them in one add_parser call
            seen[id(module)] = module
            module.add_parser(sub)
    return parser


def _models(args) -> int:
    manager = ModelManager()
    try:
        if args.action == "status":
            print("FLOW MODELS\n")
            for item in manager.status(args.target):
                print(f"{item['name']}\nStatus        {item['status']}\nPurpose       {item['purpose']}\nPath          {item['path']}\n")
            hardware = manager.hardware()
            print(f"Runtime       {hardware['architecture']} / MLX={'available' if hardware['mlx_available'] else 'unavailable'}")
        elif args.action == "remove":
            if not args.target:
                raise ValueError("models remove requires vision or voice")
            manager.remove(args.target)
            print(f"Removed {MODEL_REGISTRY[args.target].name}")
        else:
            targets = [args.target] if args.target else list(MODEL_REGISTRY)
            for target in targets:
                print(f"Installing {MODEL_REGISTRY[target].name}...")
                item = manager.install(target, args.variant)[0]
                print(f"{item['name']}: {item['status']}")
    except (RuntimeError, ValueError) as exc:
        print(f"flow models: {exc}", file=sys.stderr)
        return 2
    return 0


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    plugin = _plugins().get(args.command)
    if plugin is not None:
        return plugin.run(args)
    if args.command == "version":
        print(VERSION)
        return 0
    if args.command == "models":
        return _models(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
