"""Artifact vocabulary: four statuses only, and a structural/privacy validator for the JSON."""

from __future__ import annotations

from typing import Any, Iterable

VERIFIED, FAILED, NOT_CONFIGURED, SKIPPED = "verified", "failed", "not_configured", "skipped"
STATUSES = frozenset({VERIFIED, FAILED, NOT_CONFIGURED, SKIPPED})

CHECKS = ("env", "permissions", "models", "observer", "vision", "voice", "resources",
          "drift", "blocker", "privacy", "injection", "cloud")
SCENARIOS = ("drift", "blocker", "privacy", "injection")
SECTION_FOR = {"env": "environment", "permissions": "permissions", "models": "models",
               "observer": "screen_capture", "vision": "vision", "voice": "voice",
               "resources": "resources", "cloud": "cloud"}

FORBIDDEN_KEYS = frozenset({"image", "image_bytes", "screenshot", "pixels", "frame_bytes", "image_base64"})
MAX_STRING = 2048


def section(status: str, **fields: Any) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"invalid status {status!r}")
    return {"status": status, **fields}


def overall(sections: Iterable[dict[str, Any]]) -> tuple[str, dict[str, int]]:
    counts = {status: 0 for status in (VERIFIED, FAILED, NOT_CONFIGURED, SKIPPED)}
    for item in sections:
        counts[item["status"]] += 1
    if counts[FAILED]:
        return FAILED, counts
    if counts[VERIFIED] and not counts[NOT_CONFIGURED] and not counts[SKIPPED]:
        return VERIFIED, counts
    if counts[NOT_CONFIGURED]:
        return NOT_CONFIGURED, counts
    return (SKIPPED if counts[SKIPPED] else NOT_CONFIGURED), counts


def all_sections(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    found = [artifact[name] for name in SECTION_FOR.values() if name in artifact]
    found.extend(artifact.get("scenarios", {}).values())
    return found


def validate_artifact(artifact: dict[str, Any]) -> list[str]:
    """Return a list of problems: invalid statuses, missing keys, or anything that looks like pixels."""
    problems: list[str] = []
    for key in ("schema_version", "platform", "architecture", "flow_version", "screen_capture", "vision",
                "voice", "permissions", "models", "resources", "scenarios", "overall"):
        if key not in artifact:
            problems.append(f"missing key: {key}")
    for name in SCENARIOS:
        if name not in artifact.get("scenarios", {}):
            problems.append(f"missing scenario: {name}")
    for item in all_sections(artifact):
        if item.get("status") not in STATUSES:
            problems.append(f"invalid status: {item.get('status')!r}")
    if artifact.get("overall") not in STATUSES:
        problems.append("invalid overall status")

    def walk(value: Any, path: str) -> None:
        if isinstance(value, (bytes, bytearray)):
            problems.append(f"raw bytes at {path}")
        elif isinstance(value, str):
            if len(value) > MAX_STRING:
                problems.append(f"oversized string at {path}")
        elif isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold() in FORBIDDEN_KEYS:
                    problems.append(f"forbidden key {key!r} at {path}")
                walk(item, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(artifact, "$")
    return problems
