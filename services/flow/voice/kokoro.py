"""Optional Kokoro adapter loaded only when the voice extra is installed."""

from __future__ import annotations


class KokoroVoiceEngine:
    def __init__(self, voice: str = "af_heart") -> None:
        self.voice = voice
        self._pipeline = None

    async def speak(self, text: str) -> None:
        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise RuntimeError("install FLOW voice support with: pip install 'flow-agent[voice]'") from exc
        if self._pipeline is None:
            self._pipeline = KPipeline(lang_code="a")
        # Kokoro's generator and platform audio playback vary by release. Keep
        # this adapter explicit; callers can supply a player in the next layer.
        chunks = list(self._pipeline(text, voice=self.voice))
        if not chunks:
            raise RuntimeError("Kokoro returned no audio")
