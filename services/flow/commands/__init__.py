"""CLI command plug-ins.

Every module in this package that defines ``NAME`` (or ``NAMES`` for several commands), ``add_parser(subparsers)``
and ``run(args) -> int`` is registered automatically by ``services.flow.cli``; a module with ``NAMES`` dispatches
on ``args.command`` inside ``run``. Add a command by dropping a module here; never edit the command dispatch in
``cli.py`` for a new command.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from types import ModuleType


def command_names(module: ModuleType) -> list[str]:
    names = getattr(module, "NAMES", None)
    if names:
        return list(names)
    return [module.NAME] if hasattr(module, "NAME") else []


def discover() -> dict[str, ModuleType]:
    found: dict[str, ModuleType] = {}
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda item: item.name):
        try:
            module = importlib.import_module(f"{__name__}.{info.name}")
        except Exception as exc:  # noqa: BLE001 - one broken plug-in must not take the whole CLI down
            print(f"flow: command module {info.name!r} failed to load: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if hasattr(module, "add_parser") and hasattr(module, "run"):
            for name in command_names(module):
                found[name] = module
    return found
