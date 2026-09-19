"""Adaptive, bounded sampling scheduler independent of any capture backend."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SamplerConfig:
    base_interval: float = 10.0
    burst_interval: float = 3.0
    focus_interval: float = 20.0
    max_interval: float = 30.0
    jitter: float = 0.0


class AdaptiveSampler:
    def __init__(self, config: SamplerConfig | None = None, rng: random.Random | None = None) -> None:
        self.config = config or SamplerConfig()
        self.rng = rng or random.Random()
        self._stable = 0

    def next_interval(self, *, context_changed: bool = False, drift_possible: bool = False,
                      focused: bool = False) -> float:
        if context_changed or drift_possible:
            interval = self.config.burst_interval
            self._stable = 0
        elif focused:
            interval = self.config.focus_interval
            self._stable += 1
        else:
            interval = self.config.base_interval
            self._stable += 1
        interval = min(self.config.max_interval, max(0.1, interval))
        if self.config.jitter:
            interval *= 1 + self.rng.uniform(-self.config.jitter, self.config.jitter)
        return max(0.1, interval)
