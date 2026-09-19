"""Replaceable local voice interface. Voice failure never owns session state."""

from __future__ import annotations

from typing import Protocol


class VoiceEngine(Protocol):
    async def speak(self, text: str) -> None: ...


class MockVoiceEngine:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def speak(self, text: str) -> None:
        self.messages.append(text)
