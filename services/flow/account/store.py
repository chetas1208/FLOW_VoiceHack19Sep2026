"""Small repository contract and an in-memory implementation for tests/dev.

Production deployments should implement this contract with the SQL in the
account migration. Keeping the service independent of a database driver makes
the CLI and security tests deterministic and keeps psycopg optional locally.
"""

from __future__ import annotations

from collections.abc import Iterable
from threading import RLock

from .models import CLIAuthRequest, Device, Presence, Profile, RefreshCredential


class AccountStore:
    def __init__(self) -> None:
        self.lock = RLock()
        self.profiles: dict[str, Profile] = {}
        self.devices: dict[str, Device] = {}
        self.presence: dict[str, Presence] = {}
        self.requests: dict[str, CLIAuthRequest] = {}
        self.credentials: dict[str, RefreshCredential] = {}

    def user_devices(self, user_id: str) -> Iterable[Device]:
        return (d for d in self.devices.values() if d.user_id == user_id)
