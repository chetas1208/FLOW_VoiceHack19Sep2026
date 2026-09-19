"""Frontmost application/window metadata: helper first, ``lsappinfo`` fallback (no window title)."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from ..base import ObserverContext
from .errors import CaptureFailed
from .helper import Helper
from .runner import Runner, run

LSAPPINFO = "/usr/bin/lsappinfo"
_LINE = re.compile(r'^\s*"?([A-Za-z_]+)"?\s*=\s*"?([^"\n]*?)"?\s*$')
_NAME_KEYS = {"lsdisplayname", "name", "displayname"}
_BUNDLE_KEYS = {"cfbundleidentifier", "bundleid", "bundleidentifier"}


def context_from_helper(payload: dict[str, Any]) -> ObserverContext:
    display = payload.get("display_id")
    return ObserverContext(payload.get("application"), payload.get("bundle_id"), payload.get("window_title"),
                           None if display is None else str(display))


def parse_lsappinfo(text: str) -> tuple[str | None, str | None]:
    name = bundle = None
    for line in text.splitlines():
        match = _LINE.match(line)
        if not match:
            continue
        key, value = match.group(1).casefold(), match.group(2).strip()
        if key in _NAME_KEYS and value:
            name = value
        elif key in _BUNDLE_KEYS and value and value != "[ NULL ]":
            bundle = value
    return name, bundle


def context_from_cli(runner: Runner = run, timeout: float = 5.0) -> ObserverContext:
    front = runner([LSAPPINFO, "front"], timeout)
    asn = front.stdout.decode("utf-8", "replace").strip()
    if front.returncode != 0 or not asn:
        raise CaptureFailed("lsappinfo could not report the frontmost application")
    info = runner([LSAPPINFO, "info", "-only", "name", "-only", "bundleid", asn], timeout)
    name, bundle = parse_lsappinfo(info.stdout.decode("utf-8", "replace"))
    return ObserverContext(name, bundle, None, None)


async def active_window(helper: Helper | None = None, runner: Runner = run) -> ObserverContext:
    if helper is not None:
        return context_from_helper(await asyncio.to_thread(helper.call, "context"))
    return await asyncio.to_thread(context_from_cli, runner)
