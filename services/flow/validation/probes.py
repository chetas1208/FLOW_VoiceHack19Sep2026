"""Individual validation probes. Each returns one artifact section with an honest status.

Anything that needs a real Mac (ScreenCaptureKit, TCC permissions, MLX inference) reports
``not_configured`` on other hosts. Nothing here ever includes screenshot content.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import statistics
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit

from ..models_registry import ModelManager
from ..observer.macos.errors import HelperMissing, ObserverError
from ..observer.macos.helper import find_helper
from ..observer.macos.permissions import screen_recording_status
from .context import ValidationContext
from .model import FAILED, NOT_CONFIGURED, SKIPPED, VERIFIED, section

MACOS_ONLY = "requires macOS; this host is {system}"


def flow_version() -> str:
    try:
        from ..cli import VERSION
        return str(VERSION)
    except Exception:  # pragma: no cover - defensive; the artifact must still be produced
        try:
            from importlib.metadata import version
            return version("flow-agent")
        except Exception:
            return "unknown"


def _memory_total_mb(ctx: ValidationContext) -> int | None:
    try:
        if ctx.is_macos:
            out = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                 timeout=5, check=False).stdout.strip()
            return int(out) // (1024 * 1024)
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        return None


def platform_fields(ctx: ValidationContext) -> dict[str, Any]:
    return {"platform": ctx.system(), "architecture": ctx.machine(), "flow_version": flow_version(),
            "python_version": platform.python_version()}


# -- environment -----------------------------------------------------------------------------
def check_environment(ctx: ValidationContext) -> dict[str, Any]:
    system, machine = ctx.system(), ctx.machine()
    details: dict[str, Any] = {"os": system, "architecture": machine, "python": platform.python_version(),
                               "apple_silicon": system == "Darwin" and machine == "arm64",
                               "memory_total_mb": _memory_total_mb(ctx)}
    if system != "Darwin":
        return section(NOT_CONFIGURED, reason=MACOS_ONLY.format(system=system), **details)
    version = ctx.mac_version()
    details["os_version"] = version
    try:
        major = int(version.split(".")[0])
    except ValueError:
        return section(FAILED, reason="cannot determine macOS version", **details)
    helper = find_helper(env=ctx.env)
    details["helper_found"] = helper is not None
    warnings = []
    if major < 13:
        return section(FAILED, reason="macOS 13 or newer is required", **details)
    if major < 14:
        warnings.append("macOS 13: ScreenCaptureKit screenshots need 14+; the screencapture fallback is used")
    if machine != "arm64":
        warnings.append("Intel Mac: MLX acceleration is unavailable")
    if helper is None:
        warnings.append("flow-macos-observer helper not found; using the screencapture fallback (main display only)")
    return section(VERIFIED, warnings=warnings, **details)


# -- permissions -----------------------------------------------------------------------------
def check_permissions(ctx: ValidationContext) -> dict[str, Any]:
    if not ctx.is_macos:
        return section(NOT_CONFIGURED, reason=MACOS_ONLY.format(system=ctx.system()), states={})
    status = screen_recording_status(system=ctx.system)
    states = {"screen_recording": status.screen_recording, "accessibility": status.accessibility,
              "microphone": status.microphone, "notifications": status.notifications}
    if status.screen_recording == "granted":
        return section(VERIFIED, states=states, source=status.source)
    if status.screen_recording == "denied":
        return section(FAILED, states=states, source=status.source,
                       reason="Screen Recording denied", hint="flow permissions open")
    return section(NOT_CONFIGURED, states=states, source=status.source,
                   reason="permission state could not be read (no helper, no CoreGraphics)")


# -- models ----------------------------------------------------------------------------------
def check_models(ctx: ValidationContext) -> dict[str, Any]:
    manager = ModelManager(ctx.env.get("FLOW_MODEL_DIR"))
    items: dict[str, Any] = {}
    for entry in manager.status():
        status = {"ready": VERIFIED, "missing": NOT_CONFIGURED, "corrupt": FAILED}.get(entry["status"], FAILED)
        items[entry["key"]] = section(status, model=entry["name"], version=entry["version"],
                                      installed=entry["status"] == "ready",
                                      memory_estimate_mb=entry["memory_estimate_mb"])
    states = {item["status"] for item in items.values()}
    top = FAILED if FAILED in states else NOT_CONFIGURED if NOT_CONFIGURED in states else VERIFIED
    missing = [key for key, item in items.items() if item["status"] != VERIFIED]
    fields: dict[str, Any] = {"reason": f"not ready: {', '.join(missing)} (flow models install)"} if missing else {}
    return section(top, items=items, note="file presence and manifest only; inference is checked by vision/voice",
                   **fields)


# -- screen capture / observer ---------------------------------------------------------------
async def _observe(ctx: ValidationContext, captures: int) -> dict[str, Any]:
    if ctx.observer_factory is not None:
        observer: Any = ctx.observer_factory()
    else:
        from ..observer.macos import MacOSObserver
        observer = MacOSObserver()
    latencies: list[float] = []
    sizes: list[tuple[int, int]] = []
    displays: list[dict[str, Any]] = []
    try:
        await observer.start()
        displays = [item.to_dict() for item in await observer.displays()]
        context = await observer.active_context()
        for _ in range(captures):
            started = time.perf_counter()
            frame = await observer.snapshot()
            if frame is None:
                return section(FAILED, reason="observer returned no frame (frontmost app excluded?)",
                               backend=observer.backend, displays=displays, latency_ms=None)
            latencies.append((time.perf_counter() - started) * 1000)
            sizes.append((frame.width, frame.height))
            frame.discard_pixels()
        return section(VERIFIED, backend=observer.backend, latency_ms=round(statistics.median(latencies), 1),
                       latency_samples=len(latencies), displays=displays, frame_size=list(sizes[-1]),
                       application_detected=bool(context.application),
                       window_title_available=bool(context.window_title),
                       display_targeting="frontmost-window" if observer.backend == "helper" else "main-only")
    except HelperMissing as exc:
        return section(NOT_CONFIGURED, error=exc.to_dict(), displays=displays, latency_ms=None)
    except ObserverError as exc:
        return section(FAILED, error=exc.to_dict(), displays=displays, latency_ms=None)
    finally:
        try:
            await observer.stop()
        except Exception:
            pass


def check_screen_capture(ctx: ValidationContext, captures: int = 3) -> dict[str, Any]:
    if not ctx.is_macos:
        return section(NOT_CONFIGURED, reason=MACOS_ONLY.format(system=ctx.system()), backend=None,
                       latency_ms=None, displays=[])
    return asyncio.run(_observe(ctx, captures))


# -- vision / voice --------------------------------------------------------------------------
_STATUS_WORDS = {"verified": VERIFIED, "ok": VERIFIED, "pass": VERIFIED, "passed": VERIFIED,
                 "success": VERIFIED, "ready": VERIFIED, "failed": FAILED, "fail": FAILED, "error": FAILED,
                 "not_configured": NOT_CONFIGURED, "not-configured": NOT_CONFIGURED, "unconfigured": NOT_CONFIGURED,
                 "skipped": SKIPPED}


def _last_json(text: str) -> dict[str, Any] | None:
    for line in reversed([item for item in text.splitlines() if item.strip()]):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        return None


def _number(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(float(value), 1)
    return None


def check_flow_test(ctx: ValidationContext, kind: str) -> dict[str, Any]:
    """Run ``flow <kind> test --json`` (owned by the vision/voice commands) and normalise the result."""
    empty = {"model": None, "latency_ms": None}
    if kind == "vision":
        empty["memory_mb"] = None
    if not ctx.is_macos:
        return section(NOT_CONFIGURED, reason=MACOS_ONLY.format(system=ctx.system()), **empty)
    result = ctx.measure([*ctx.flow_command, kind, "test", "--json"], ctx.model_timeout, ctx.env)
    if result.timed_out:
        return section(FAILED, reason=f"flow {kind} test timed out after {ctx.model_timeout:g}s", **empty)
    payload = _last_json(result.stdout)
    if payload is None:
        stderr = result.stderr
        absent = result.returncode == 2 and any(word in stderr for word in
                                                 ("invalid choice", "unrecognized arguments", "usage:"))
        if absent:
            return section(NOT_CONFIGURED, reason=f"`flow {kind} test --json` is not available in this build", **empty)
        return section(FAILED, reason=f"no JSON from flow {kind} test (exit {result.returncode})",
                       exit_code=result.returncode, **empty)
    raw = str(payload.get("status", "")).strip().lower()
    status = _STATUS_WORDS.get(raw) or (VERIFIED if result.returncode == 0 else
                                        NOT_CONFIGURED if result.returncode == 2 else FAILED)
    if status == VERIFIED and result.returncode != 0:
        status = FAILED  # never trust a verified claim from a failing process
    fields: dict[str, Any] = {"model": payload.get("model") if isinstance(payload.get("model"), str) else None,
                              "latency_ms": _number(payload, "latency_ms", "total_latency_ms"),
                              "exit_code": result.returncode}
    if kind == "vision":
        reported = _number(payload, "memory_mb", "peak_rss_mb", "rss_mb")
        fields["memory_mb"] = reported if reported is not None else round(result.peak_rss_mb, 1)
        fields["memory_source"] = "reported" if reported is not None else "measured_peak_rss"
    if status != VERIFIED:
        reason = payload.get("reason") or payload.get("error")
        fields["reason"] = str(reason)[:300] if reason else f"flow {kind} test reported {raw or 'no status'}"
    return section(status, **fields)


# -- cloud -----------------------------------------------------------------------------------
def _http_get(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "flow-validate"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-provided URL
            return response.status, response.read(512).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def check_cloud(ctx: ValidationContext) -> dict[str, Any]:
    url = ctx.env.get("FLOW_API_URL")
    if not url:
        return section(NOT_CONFIGURED, reason="FLOW_API_URL is not set; cloud is optional")
    parts = urlsplit(url)
    target = {"scheme": parts.scheme, "host": parts.hostname}
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return section(FAILED, reason="FLOW_API_URL is not a valid http(s) URL", **target)
    getter = ctx.http_get or _http_get
    started = time.perf_counter()
    try:
        code, _ = getter(f"{parts.scheme}://{parts.netloc}/health/ready", ctx.cloud_timeout)
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return section(FAILED, reason=f"unreachable: {type(exc).__name__}", **target)
    latency = round((time.perf_counter() - started) * 1000, 1)
    if code == 200:
        return section(VERIFIED, http_status=code, latency_ms=latency, **target)
    return section(FAILED, http_status=code, latency_ms=latency, reason="health/ready did not return 200", **target)
