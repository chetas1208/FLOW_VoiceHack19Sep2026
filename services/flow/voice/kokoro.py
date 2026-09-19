"""Optional Kokoro adapter loaded only when the voice extra is installed."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from ..models_registry import ModelManager


class KokoroVoiceEngine:
    def __init__(self, voice: str = "af_heart", model_root: str | Path | None = None,
                 player=None) -> None:
        self.voice = voice
        self.model_root = Path(model_root) if model_root else ModelManager().path("voice")
        self.player = player or self._play_system
        self._pipeline = None

    def load(self) -> None:
        if self._pipeline is not None:
            return
        if not self.model_root.is_dir():
            raise RuntimeError("Kokoro is not installed; run: flow models install voice")
        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise RuntimeError("install FLOW voice support with: pip install 'flow-agent[voice]'") from exc
        self._pipeline = KPipeline(lang_code="a")

    def synthesize(self, text: str):
        self.load()
        chunks = list(self._pipeline(text, voice=self.voice))
        audio = next((chunk[-1] for chunk in reversed(chunks) if hasattr(chunk[-1], "dtype") or hasattr(chunk[-1], "tobytes")), None)
        if audio is None:
            raise RuntimeError("Kokoro returned no audio")
        return audio

    @staticmethod
    def _play_system(audio) -> None:
        try:
            import sounddevice
        except ImportError as exc:
            raise RuntimeError("audio playback requires sounddevice or a platform player") from exc
        sounddevice.play(audio, 24000, blocking=True)

    async def speak(self, text: str) -> None:
        audio = await asyncio.to_thread(self.synthesize, text)
        await asyncio.to_thread(self.player, audio)
