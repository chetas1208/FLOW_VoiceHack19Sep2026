"""Stable interface for local multimodal intelligence engines."""

from __future__ import annotations

from typing import Any, Protocol

from ..observer.frame import CapturedFrame


class IntelligenceEngine(Protocol):
    async def observe(self, goal: str, frame: CapturedFrame, context: dict[str, Any],
                      history: list[dict[str, Any]]) -> Any: ...

    async def reason(self, question: str, context: dict[str, Any]) -> dict[str, Any]: ...

    async def recommend(self, context: dict[str, Any]) -> dict[str, Any]: ...

    async def plan_task(self, instruction: str, context: dict[str, Any]) -> dict[str, Any]: ...

    async def evaluate_tool_result(self, result: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]: ...
