"""Deterministic temporal reasoning over semantic vision observations.

Everything here is a pure function of the observations (and their timestamps) fed to ``update``:

* drift state machine  ``focused / mixed / possible_drift / sustained_drift / recovering``
* temporal blocker detector (>=4 consecutive aligned, non-progressing, same-signature observations spanning ~3 min)
* goal versions: ``set_goal`` stamps later observations with a new ``goal_version``; history is never rescored
* human vs agent activity: agent time lives in its own lane and never touches human focus/score
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from ..models import ActivityCategory, Observation, ensure_utc, iso
from ..temporal import TaskSegmenter
from ..vision.sanitize import normalize_signature, sanitize_screen_text, signature_similarity
from ..vision.schema import VisionActivityType, VisionObservation


class Recommendation(str, Enum):
    NONE = "none"
    REMIND_GOAL = "remind_goal"
    RETURN_TO_LAST_TASK = "return_to_last_task"
    SUMMARIZE_LAST_PROGRESS = "summarize_last_progress"
    SUGGEST_NEXT_STEP = "suggest_next_step"
    FLAG_POSSIBLE_BLOCKER = "flag_possible_blocker"
    RECOMMEND_BREAK = "recommend_break"
    ASK_CLARIFY_GOAL = "ask_clarify_goal"


class Drift:
    FOCUSED = "focused"
    MIXED = "mixed"
    POSSIBLE = "possible_drift"
    SUSTAINED = "sustained_drift"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"
    DRIFT_STATES = frozenset({"possible_drift", "sustained_drift", "drifting"})  # "drifting" is the legacy spelling


@dataclass(frozen=True, slots=True)
class EfficiencyConfig:
    aligned_threshold: float = .7
    low_alignment: float = .4
    sustained_drift_seconds: float = 120.0
    recovery_observations: int = 2
    blocker_min_observations: int = 4
    blocker_min_span_seconds: float = 170.0   # "about three minutes" with sampling jitter
    blocker_progress_max: float = .25
    blocker_similarity: float = .5
    max_gap_seconds: float = 300.0            # a longer silence breaks a run: the observer was not watching
    history_limit: int = 500


@dataclass(frozen=True, slots=True)
class GoalRepresentation:
    primary_goal: str
    keywords: tuple[str, ...]
    success_signals: tuple[str, ...]

    @classmethod
    def from_text(cls, goal: str) -> "GoalRepresentation":
        words = [word.casefold() for word in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,}", goal)]
        return cls(goal.strip(), tuple(dict.fromkeys(words)), ("tests pass", "completed", "resolved"))


@dataclass(frozen=True, slots=True)
class GoalVersionRecord:
    version: int
    goal: GoalRepresentation
    effective_at: datetime | None       # None: applies from the very first observation
    source: str = "cli"

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "goal": self.goal.primary_goal,
                "effective_at": iso(self.effective_at) if self.effective_at else None, "source": self.source}


@dataclass(frozen=True, slots=True)
class AgentInterval:
    task_id: str
    start: datetime
    end: datetime
    label: str = ""

    @property
    def seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "label": self.label, "start": iso(self.start), "end": iso(self.end),
                "duration_seconds": self.seconds}


@dataclass(slots=True)
class EfficiencyState:
    goal: GoalRepresentation
    current_task: str | None = None
    current_task_phase: str = "unknown"
    alignment: float | None = None
    progress: float | None = None
    focus_continuity: float | None = None
    context_stability: float | None = None
    drift_state: str = "unknown"
    idle_state: str = "active"
    coverage: float = 0.0
    confidence: float = 0.0
    last_intervention: datetime | None = None
    last_high_alignment_task: str | None = None
    last_progress_event: str | None = None
    session_score: float | None = None
    recommendation: Recommendation = Recommendation.NONE
    blocker: str | None = None
    observations: list[Observation] = field(default_factory=list)
    goal_version: int = 1
    drift_seconds: float = 0.0
    blocker_evidence: dict[str, Any] | None = None
    context_switches: int = 0


def _vision(observation: Observation) -> dict[str, Any]:
    return (observation.metadata or {}).get("vision") or {}


class EfficiencyEngine:
    def __init__(self, goal: str, config: EfficiencyConfig | None = None) -> None:
        self.config = config or EfficiencyConfig()
        self.state = EfficiencyState(GoalRepresentation.from_text(goal))
        self.goal_history: list[GoalVersionRecord] = [GoalVersionRecord(1, self.state.goal, None, "initial")]
        self.agent_intervals: list[AgentInterval] = []
        self._counter = 0

    # -- goal versions ------------------------------------------------------------------------------
    @property
    def goal_version(self) -> int:
        return self.state.goal_version

    def set_goal(self, goal: str, effective_at: datetime | None = None, source: str = "cli") -> int:
        """Start a new goal version. Earlier observations keep the version (and scores) they were made under."""
        effective = ensure_utc(effective_at) if effective_at else datetime.now(timezone.utc)
        record = GoalVersionRecord(self.state.goal_version + 1, GoalRepresentation.from_text(goal), effective, source)
        self.goal_history.append(record)
        self.state.goal, self.state.goal_version = record.goal, record.version
        # Nothing observed yet is evidence about the new goal.
        self.state.drift_state, self.state.drift_seconds = Drift.UNKNOWN, 0.0
        self.state.blocker = self.state.blocker_evidence = None
        self.state.recommendation = Recommendation.NONE
        self.state.alignment = self.state.progress = self.state.session_score = None
        return record.version

    def _record_at(self, timestamp: datetime) -> GoalVersionRecord:
        stamp = ensure_utc(timestamp)
        chosen = self.goal_history[0]
        for record in self.goal_history[1:]:
            if record.effective_at is not None and record.effective_at <= stamp:
                chosen = record
        return chosen

    # -- scoring --------------------------------------------------------------------------------------
    def _alignment(self, vision: VisionObservation, goal: GoalRepresentation | None = None) -> tuple[float | None, ActivityCategory]:
        goal = goal or self.state.goal
        if vision.relevance is not None:
            value = max(0.0, min(1.0, vision.relevance))
        else:
            content = f"{vision.activity} {' '.join(vision.visible_evidence)}".casefold()
            matches = sum(1 for word in goal.keywords if word in content)
            if matches:
                value = min(.95, .55 + matches * .12)
            elif vision.activity_type in {VisionActivityType.UNKNOWN, VisionActivityType.WAITING}:
                return None, ActivityCategory.UNKNOWN
            elif vision.activity_type in {VisionActivityType.RESEARCH, VisionActivityType.DOCUMENTATION, VisionActivityType.COMMUNICATION}:
                value = .55
            else:
                value = .15
        if value >= .7:
            return value, ActivityCategory.CORE_TASK if vision.activity_type in {VisionActivityType.IMPLEMENTATION, VisionActivityType.DEBUGGING, VisionActivityType.TESTING, VisionActivityType.REVIEW} else ActivityCategory.SUPPORTING_TASK
        if value >= .4:
            return value, ActivityCategory.NEUTRAL
        return value, ActivityCategory.DISTRACTION

    def _current(self) -> list[Observation]:
        return [item for item in self.state.observations
                if (item.metadata or {}).get("goal_version", 1) == self.state.goal_version]

    def update(self, vision: VisionObservation, idle_state: str = "active") -> Observation:
        record = self._record_at(vision.timestamp)
        stamped = replace(vision, goal_version=record.version)
        alignment, category = self._alignment(stamped, record.goal)
        self._counter += 1
        observation = Observation("obs_eff_" + str(self._counter - 1), "", vision.timestamp,
            vision.source, vision.application, vision.window_title, vision.activity, category,
            alignment, vision.progress_signal, vision.confidence,
            {"vision": stamped.to_dict(), "goal_version": record.version})
        state = self.state
        state.observations.append(observation)
        state.observations = state.observations[-self.config.history_limit:]
        if record.version != state.goal_version:
            return observation  # a late observation for an older goal: kept as history, never scored as current
        state.current_task, state.current_task_phase = vision.activity, vision.task_phase
        state.alignment, state.progress, state.idle_state = alignment, vision.progress_signal, idle_state
        if alignment is not None and alignment >= self.config.aligned_threshold:
            state.last_high_alignment_task = vision.activity
        if vision.progress_signal is not None and vision.progress_signal >= .7:
            state.last_progress_event = vision.activity
        current = self._current()
        state.coverage = sum(item.goal_alignment is not None for item in current) / max(1, len(current))
        confidences = [item.confidence for item in current if item.confidence is not None]
        state.confidence = sum(confidences) / len(confidences) if confidences else 0.0
        state.drift_state, state.drift_seconds = self._drift(current)
        state.context_stability, state.focus_continuity, state.context_switches = self._stability(current)
        state.blocker, state.blocker_evidence = self._blocker(current, vision)
        state.recommendation = self._recommendation()
        if (alignment is not None and state.focus_continuity is not None and state.context_stability is not None
                and state.progress is not None):
            state.session_score = 100 * (.4 * alignment + .25 * state.focus_continuity + .15 * state.context_stability + .2 * state.progress)
        else:
            state.session_score = None
        return observation

    # -- drift ------------------------------------------------------------------------------------------
    def _drift(self, observations: list[Observation], now: datetime | None = None) -> tuple[str, float]:
        usable = [item for item in observations if item.goal_alignment is not None]
        if not usable:
            return Drift.UNKNOWN, 0.0
        cfg = self.config
        index = len(usable) - 1
        while index >= 0 and usable[index].goal_alignment < cfg.low_alignment:
            index -= 1
        low_run = usable[index + 1:]
        if low_run:
            end = ensure_utc(now) if now else ensure_utc(low_run[-1].timestamp)
            seconds = max(0.0, (end - ensure_utc(low_run[0].timestamp)).total_seconds())
            sustained = seconds >= cfg.sustained_drift_seconds and (len(low_run) >= 2 or now is not None)
            return (Drift.SUSTAINED if sustained else Drift.POSSIBLE), seconds
        trailing_end = index                                   # last non-low observation
        start = trailing_end
        while start >= 0 and usable[start].goal_alignment >= cfg.low_alignment:
            start -= 1
        trailing = usable[start + 1:]
        had_drift = start >= 0                                 # a low observation precedes the trailing run
        last = trailing[-1].goal_alignment
        aligned_tail = 0
        for item in reversed(trailing):
            if item.goal_alignment >= cfg.aligned_threshold:
                aligned_tail += 1
            else:
                break
        if had_drift and (last < cfg.aligned_threshold or aligned_tail < cfg.recovery_observations):
            return Drift.RECOVERING, 0.0
        return (Drift.FOCUSED if last >= cfg.aligned_threshold else Drift.MIXED), 0.0

    def drift_seconds(self, now: datetime | None = None) -> float:
        """Seconds of continuous low alignment ending now (or at the last observation); 0 when not drifting."""
        state, seconds = self._drift(self._current(), now)
        return seconds if state in (Drift.POSSIBLE, Drift.SUSTAINED) else 0.0

    def recent_confidence(self, window: int | timedelta = 5) -> float:
        """Mean confidence of the last ``window`` observations (count) or of the last ``window`` of time."""
        items = self._current()
        if isinstance(window, timedelta):
            if not items:
                return 0.0
            cutoff = ensure_utc(items[-1].timestamp) - window
            items = [item for item in items if ensure_utc(item.timestamp) >= cutoff]
        else:
            items = items[-max(1, int(window)):]
        values = [item.confidence for item in items if item.confidence is not None]
        return sum(values) / len(values) if values else 0.0

    def context_switch_count(self, window_seconds: float = 600.0) -> int:
        items = self._current()
        if not items:
            return 0
        cutoff = ensure_utc(items[-1].timestamp) - timedelta(seconds=window_seconds)
        apps = [item.app_name for item in items if ensure_utc(item.timestamp) >= cutoff and item.app_name]
        return sum(1 for left, right in zip(apps, apps[1:]) if left != right)

    def _stability(self, observations: list[Observation]) -> tuple[float, float, int]:
        segments = TaskSegmenter().segment(observations)
        stability = max(0.0, 1 - (max(0, len(segments) - 1) / max(1, len(observations) - 1)))
        focus = min(1.0, max((segment.to_dict()["duration_seconds"] for segment in segments
                              if segment.alignment is not None and segment.alignment >= self.config.aligned_threshold), default=0) / 300)
        return stability, focus, self.context_switch_count()

    # -- blocker ------------------------------------------------------------------------------------------
    def _signature(self, observation: Observation) -> frozenset[str]:
        vision = _vision(observation)
        return normalize_signature(vision.get("possible_blocker") or observation.activity_summary)

    def _blocker(self, observations: list[Observation], vision: VisionObservation) -> tuple[str | None, dict[str, Any] | None]:
        cfg = self.config
        if observations:
            last = observations[-1]
            aligned = last.goal_alignment is not None and last.goal_alignment >= cfg.aligned_threshold
            stalled = last.progress_signal is not None and last.progress_signal <= cfg.blocker_progress_max
            if aligned and stalled:
                signature = self._signature(last)
                run = [last]
                for previous in reversed(observations[:-1]):
                    gap = (ensure_utc(run[-1].timestamp) - ensure_utc(previous.timestamp)).total_seconds()
                    if gap > cfg.max_gap_seconds:
                        break
                    if (previous.goal_alignment is None or previous.goal_alignment < cfg.aligned_threshold
                            or previous.progress_signal is None or previous.progress_signal > cfg.blocker_progress_max
                            or signature_similarity(signature, self._signature(previous)) < cfg.blocker_similarity):
                        break
                    run.append(previous)
                span = (ensure_utc(last.timestamp) - ensure_utc(run[-1].timestamp)).total_seconds()
                if len(run) >= cfg.blocker_min_observations and span >= cfg.blocker_min_span_seconds:
                    text = _vision(last).get("possible_blocker")
                    minutes = max(1, round(span / 60))
                    if not text:
                        clean, _ = sanitize_screen_text(last.activity_summary or "the same screen", 100)
                        text = f"no visible progress on {clean} for {minutes} min"
                    return text, {"kind": "temporal", "observations": len(run), "span_seconds": span,
                                  "signature": sorted(signature)[:8], "first_seen": iso(run[-1].timestamp),
                                  "last_seen": iso(last.timestamp),
                                  "avg_progress": sum(item.progress_signal for item in run) / len(run),
                                  "avg_alignment": sum(item.goal_alignment for item in run) / len(run)}
        if vision.possible_blocker:  # single-frame evidence: reported, but weaker than a temporal detection
            return vision.possible_blocker, {"kind": "single_frame", "observations": 1, "span_seconds": 0.0,
                                             "signature": sorted(normalize_signature(vision.possible_blocker))[:8]}
        return None, None

    def _recommendation(self) -> Recommendation:
        state = self.state
        if state.blocker:  # a blocker outranks any drift reminder
            return Recommendation.FLAG_POSSIBLE_BLOCKER
        if state.drift_state == Drift.SUSTAINED and state.last_high_alignment_task:
            return Recommendation.RETURN_TO_LAST_TASK
        if state.drift_state == Drift.SUSTAINED:
            return Recommendation.REMIND_GOAL
        return Recommendation.NONE

    # -- agent activity -------------------------------------------------------------------------------------
    def record_agent_activity(self, task_id: str, start: datetime, end: datetime, label: str = "") -> AgentInterval:
        """Register time the delegated agent (not the human) spent on ``task_id``. Upserts by (task_id, start)."""
        start, end = ensure_utc(start), ensure_utc(end)
        if end < start:
            raise ValueError("agent activity must not end before it starts")
        interval = AgentInterval(task_id, start, end, label)
        self.agent_intervals = [item for item in self.agent_intervals if not (item.task_id == task_id and item.start == start)]
        self.agent_intervals.append(interval)
        self.agent_intervals.sort(key=lambda item: item.start)
        return interval

    def _human_active_windows(self, observations: list[Observation]) -> list[tuple[datetime, datetime]]:
        ordered = sorted(observations, key=lambda item: ensure_utc(item.timestamp))
        windows = []
        for left, right in zip(ordered, ordered[1:]):
            start, end = ensure_utc(left.timestamp), ensure_utc(right.timestamp)
            if 0 < (end - start).total_seconds() <= self.config.max_gap_seconds:
                windows.append((start, end))
        return windows

    # -- reporting --------------------------------------------------------------------------------------------
    def report(self) -> dict[str, Any]:
        state = self.state
        segments = [item.to_dict() for item in TaskSegmenter().segment(state.observations)]
        current = self._current()
        windows = self._human_active_windows(current)
        human_seconds = sum((end - start).total_seconds() for start, end in windows)
        parallel = 0.0
        for interval in self.agent_intervals:
            for start, end in windows:
                overlap = (min(end, interval.end) - max(start, interval.start)).total_seconds()
                parallel += max(0.0, overlap)
        agent = [item.to_dict() for item in self.agent_intervals]
        human = {"alignment": state.alignment, "progress": state.progress, "focus_continuity": state.focus_continuity,
                 "context_stability": state.context_stability, "session_score": state.session_score,
                 "drift_state": state.drift_state, "drift_seconds": state.drift_seconds,
                 "context_switches": state.context_switches, "active_seconds": human_seconds,
                 "observation_count": len(current), "segments": segments}
        return {"goal": state.goal.primary_goal, "current_task": state.current_task,
                "task_phase": state.current_task_phase, "alignment": state.alignment,
                "progress": state.progress, "focus_continuity": state.focus_continuity,
                "context_stability": state.context_stability, "drift_state": state.drift_state,
                "drift_seconds": state.drift_seconds, "coverage": state.coverage, "confidence": state.confidence,
                "session_score": state.session_score, "recommendation": state.recommendation.value,
                "blocker": state.blocker, "blocker_evidence": state.blocker_evidence, "segments": segments,
                "goal_version": state.goal_version, "goal_history": [item.to_dict() for item in self.goal_history],
                "human": human,
                "agent": {"active_seconds": sum(item.seconds for item in self.agent_intervals),
                          "task_count": len({item.task_id for item in self.agent_intervals}),
                          "intervals": agent, "parallel_with_human_seconds": parallel},
                "timeline": {"human": segments, "agent": agent}}
