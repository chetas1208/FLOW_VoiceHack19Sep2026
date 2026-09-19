"""Long-running local observation runtime and portable replay runner."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from .activity import ActivityAnalyzer
from .efficiency import EfficiencyEngine
from .models import SessionStatus
from .observer import AdaptiveSampler, ObserverPipeline, SamplerConfig
from .session_manager import SessionManager
from .temporal import TaskSegmenter, TemporalContext


@dataclass(slots=True)
class RuntimeState:
    observer: str = "starting"
    analyzer: str = "starting"
    last_error: str | None = None
    captures: int = 0
    analyses: int = 0
    skipped_frames: int = 0


class SessionRuntime:
    def __init__(self, manager: SessionManager, session_id: str, observer, analyzer: ActivityAnalyzer,
                 sampler: AdaptiveSampler | None = None, efficiency: EfficiencyEngine | None = None) -> None:
        session = manager.get_session(session_id)
        self.manager, self.session_id, self.goal = manager, session_id, session.goal
        self.observer, self.analyzer = observer, analyzer
        self.sampler = sampler or AdaptiveSampler(SamplerConfig())
        self.efficiency = efficiency or EfficiencyEngine(self.goal)
        self.pipeline = ObserverPipeline(session_id, self.goal, observer, analyzer, manager, efficiency=self.efficiency)
        self.context = TemporalContext(self.goal)
        self.state = RuntimeState()
        self._stop = asyncio.Event()

    async def run_once(self) -> Any:
        item = await self.pipeline.observe_once()
        if item is None:
            self.state.skipped_frames += 1
            return None
        self.state.captures += 1; self.state.analyses += 1
        metrics = self.manager.metrics(self.session_id)
        self.context.update(item, metrics.drift_state.value)
        return item

    async def run(self, max_cycles: int | None = None) -> None:
        await self.observer.start(); self.state.observer = "healthy"; self.state.analyzer = "healthy"
        cycles = 0
        try:
            while not self._stop.is_set() and self.manager.get_session(self.session_id).status == SessionStatus.ACTIVE:
                try:
                    await self.run_once()
                except Exception as exc:
                    self.state.last_error = f"{type(exc).__name__}: {exc}"
                    self.state.observer = "degraded"
                cycles += 1
                if max_cycles is not None and cycles >= max_cycles: break
                await asyncio.sleep(self.sampler.next_interval(focused=self.manager.metrics(self.session_id).drift_state.value == "focused"))
        finally:
            await self.observer.stop()

    def stop(self) -> None:
        self._stop.set()

    def report(self) -> dict[str, Any]:
        observations = self.manager.observations(self.session_id)
        report = self.manager.report(self.session_id)
        report["task_segments"] = [segment.to_dict() for segment in TaskSegmenter().segment(observations)]
        report["runtime"] = {"observer": self.state.observer, "analyzer": self.state.analyzer,
                             "captures": self.state.captures, "analyses": self.state.analyses,
                             "skipped_frames": self.state.skipped_frames, "last_error": self.state.last_error}
        report["efficiency"] = self.efficiency.report()
        return report
