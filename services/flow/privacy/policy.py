"""Privacy defaults: excluded applications produce metadata, never pixels."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_EXCLUSIONS = {"1password", "keychain access", "whatsapp", "messages", "lastpass"}


class PrivacyPolicy:
    def __init__(self, excluded_apps: set[str] | None = None) -> None:
        self.excluded_apps = {item.casefold() for item in (excluded_apps or DEFAULT_EXCLUSIONS)}

    def is_excluded(self, application: str | None) -> bool:
        return bool(application and application.casefold() in self.excluded_apps)

    def add_exclusion(self, application: str) -> None:
        if not application.strip():
            raise ValueError("application must not be empty")
        self.excluded_apps.add(application.casefold())

    def remove_exclusion(self, application: str) -> None:
        self.excluded_apps.discard(application.casefold())

    def to_dict(self) -> dict[str, list[str]]:
        return {"excluded_apps": sorted(self.excluded_apps)}

    def save(self, path: str | Path) -> None:
        target = Path(path); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2)); target.chmod(0o600)

    @classmethod
    def load(cls, path: str | Path) -> "PrivacyPolicy":
        try:
            return cls(set(json.loads(Path(path).read_text()).get("excluded_apps", [])))
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
