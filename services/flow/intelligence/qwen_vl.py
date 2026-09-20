"""Qwen3-VL local adapter with lazy optional runtime loading.

The default backend uses Transformers' image-text pipeline. A callable backend
can be injected for MLX-VLM or deterministic tests; no remote API is used.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from ..models_registry import ModelManager
from ..observer.frame import CapturedFrame
from .prompts import OBSERVATION_SYSTEM_PROMPT
from .schema import IntelligenceObservation


def _json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("Qwen returned no JSON object")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Qwen returned a JSON value instead of an object")
    return value


class QwenVLIntelligenceEngine:
    name = "qwen3-vl"

    def __init__(self, root: str | Path | None = None, *, backend: Callable[[Any, str], str] | None = None,
                 model_name: str | None = None) -> None:
        self.model_root = Path(root) if root else ModelManager().path("intelligence")
        self.model_name = model_name or "Qwen3-VL 4B Instruct"
        self.backend = backend
        self._pipeline = None
        self.loaded = backend is not None
        self.last_latency_ms: float | None = None

    def status(self) -> str:
        marker = self.model_root / "flow-model.json"
        return "ready" if self.loaded else ("missing" if not marker.is_file() else "not_loaded")

    def load(self) -> None:
        if self.loaded:
            return
        manager = ModelManager(self.model_root.parent)
        manager.assert_runtime_memory_budget(manager._spec("vision"))
        if not self.model_root.is_dir():
            raise RuntimeError("Qwen3-VL is not installed; run: flow models install intelligence")
        try:
            from transformers import pipeline
        except ImportError as exc:
            raise RuntimeError("Qwen3-VL requires the optional vision runtime: pip install 'flow-agent[vision]'") from exc
        self._pipeline = pipeline("image-text-to-text", model=str(self.model_root), device_map="auto")
        self.loaded = True

    def _generate(self, image: Any, prompt: str) -> str:
        if self.backend is not None:
            return self.backend(image, OBSERVATION_SYSTEM_PROMPT + "\n" + prompt)
        self.load()
        user_content = [{"type": "text", "text": prompt}]
        if image is not None:
            user_content.insert(0, {"type": "image", "image": image})
        messages = [{"role": "system", "content": [{"type": "text", "text": OBSERVATION_SYSTEM_PROMPT}]},
                    {"role": "user", "content": user_content}]
        result = self._pipeline(text=messages, max_new_tokens=256, do_sample=False)  # type: ignore[operator]
        text = result[0]["generated_text"][-1]["content"] if isinstance(result[0], dict) else str(result[0])
        return text if isinstance(text, str) else json.dumps(text)

    async def observe(self, goal: str, frame: CapturedFrame, context: dict[str, Any],
                      history: list[dict[str, Any]]) -> IntelligenceObservation:
        if not frame.image_bytes:
            raise RuntimeError("Qwen observation requires an in-memory frame")
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("Qwen3-VL requires Pillow: pip install 'flow-agent[vision]'") from exc
        image = Image.open(BytesIO(frame.image_bytes)).convert("RGB")
        prompt = json.dumps({"goal": goal, "context": context, "recent_history": history[-10:]}, ensure_ascii=True)
        started = time.perf_counter()
        raw = await asyncio.to_thread(self._generate, image, prompt)
        self.last_latency_ms = (time.perf_counter() - started) * 1000
        value = _json(raw)
        return IntelligenceObservation.from_dict(value, timestamp=frame.timestamp,
                                                   application=frame.application, window_title=frame.window_title)

    async def analyze(self, goal: str, frame: CapturedFrame, context: dict[str, Any],
                      history: list[dict[str, Any]]):
        """Compatibility adapter for ``ObserverPipeline``."""
        return (await self.observe(goal, frame, context, history)).observation

    async def _json_task(self, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        raw = await asyncio.to_thread(self._generate, None, json.dumps(payload, ensure_ascii=True))
        return _json(raw)

    async def reason(self, question: str, context: dict[str, Any]) -> dict[str, Any]:
        return await self._json_task("Answer only from supplied local evidence.", {"question": question, "context": context})

    async def recommend(self, context: dict[str, Any]) -> dict[str, Any]:
        return await self._json_task("Suggest one evidence-based next action.", {"context": context})

    async def plan_task(self, instruction: str, context: dict[str, Any]) -> dict[str, Any]:
        return await self._json_task("Create a bounded read-first task plan.", {"instruction": instruction, "context": context})

    async def evaluate_tool_result(self, result: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return await self._json_task("Evaluate the tool result; do not invent success.", {"result": result, "context": context})
