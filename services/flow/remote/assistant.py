"""Deterministic, evidence-backed session assistant.

``answer(question, ctx)`` never calls a model and never invents facts: every sentence is built from a field of
``AssistantContext`` (which the daemon assembles from the session's real state) and the supporting facts are
returned in ``AssistantAnswer.evidence``. Questions it cannot ground get an honest fallback that lists what it can
answer. ``ask`` is chat only: nothing in this module can start a task or change anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from typing import Any

from ..models import utc_now

SUPPORTED_QUESTIONS = (
    "what am I doing",
    "what did I finish",
    "why did my score drop",
    "what should I do next",
    "what is blocking me",
    "what did the agent complete",
    "how long was I away",
    "what changed while I was away",
)


# ---- small shared helpers (also used by attach_render) --------------------------------------------
def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def clock_str(value: Any, tz: tzinfo | None = None) -> str:
    moment = parse_time(value)
    return moment.astimezone(tz).strftime("%H:%M") if moment else "--:--"


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    seconds = max(0, int(round(seconds)))
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def _pct(value: Any) -> str:
    return f"{float(value):.0%}" if isinstance(value, (int, float)) else "unavailable"


def _text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ---- data -----------------------------------------------------------------------------------------
@dataclass
class AssistantContext:
    """Everything the assistant may cite. Plain data, built by the daemon; all fields optional."""

    session_id: str = ""
    goal: str | None = None
    goal_state: str | None = None
    status: str | None = None
    now: datetime = field(default_factory=utc_now)
    tz: tzinfo | None = None                          # None = the machine's local zone
    metrics: dict[str, Any] = field(default_factory=dict)
    score_history: list[dict[str, Any]] = field(default_factory=list)   # [{"timestamp", "session_score"}]
    segments: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)     # most recent last
    blocker: str | dict[str, Any] | None = None
    drift: dict[str, Any] | None = None                                  # {"state", "since"}
    tasks: list[dict[str, Any]] = field(default_factory=list)            # DelegatedTask dicts (with result)
    recommendations: list[dict[str, Any]] = field(default_factory=list)  # ActionRecommendation dicts
    approvals: list[dict[str, Any]] = field(default_factory=list)        # ActionApproval dicts
    away_periods: list[dict[str, Any]] = field(default_factory=list)     # {"start","end"|None,"analysis_paused"}
    subtasks: list[dict[str, Any]] = field(default_factory=list)         # Subtask dicts


@dataclass
class AssistantAnswer:
    text: str
    evidence: list[str] = field(default_factory=list)
    intent: str = "unknown"

    @property
    def grounded(self) -> bool:
        return self.intent != "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "evidence": list(self.evidence), "intent": self.intent}


# ---- intent ---------------------------------------------------------------------------------------
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple((name, re.compile(pattern)) for name, pattern in (
    ("away_summary", r"while i (was|were) (away|gone|out)|what (changed|happened|did i miss)|catch me up|missed|welcome back"),
    ("away_duration", r"how (long|much time).*(away|gone|out|break)|(away|gone) for how long|how long (have|has) i been (away|gone)"),
    ("agent", r"\b(agent|delegat\w*|assistant|flow)\b.*\b(complet\w*|did|done|finish\w*|run|ran|found)\b|"
              r"\b(complet\w*|finish\w*|done)\b.*\bagent\b|what tasks|task results?"),
    ("score", r"\bscore\b|\bdrop(ped)?\b|\bwhy (am i|is my|did my|has my)\b.*(low|worse|down|lower|drift)|why.*(drift|distract)"),
    ("blocker", r"block(ed|ing|er)?\b|\bstuck\b|what'?s in (my|the) way|holding me"),
    ("next", r"what should i (do|work on|focus)|\bnext\b|recommend\w*|what now|suggest\w*"),
    ("finished", r"what (did|have) i (finish\w*|complet\w*|do|done|accomplish\w*|get done)|accomplish\w*|what.*(finished|completed|done)\b|progress|how far"),
    ("doing", r"what (am|are) i (doing|working|up to)|what'?s (my )?current|right now|working on|current(ly)? (doing|task|activity)"),
))


def classify(question: str) -> str:
    text = " ".join(question.lower().split())
    for name, pattern in _RULES:
        if pattern.search(text):
            return name
    return "unknown"


# ---- answers --------------------------------------------------------------------------------------
def answer(question: str, ctx: AssistantContext) -> AssistantAnswer:
    intent = classify(question or "")
    handler = _HANDLERS.get(intent)
    if handler is None:
        return _fallback()
    result = handler(ctx)
    result.intent = intent
    return result


def _fallback() -> AssistantAnswer:
    listing = "\n".join(f"  - {item}" for item in SUPPORTED_QUESTIONS)
    return AssistantAnswer("I can't answer that from what I've recorded in this session, and I won't guess. "
                           f"I can answer questions like:\n{listing}", [], "unknown")


def _latest_observation(ctx: AssistantContext) -> dict[str, Any] | None:
    items = [item for item in ctx.observations if isinstance(item, dict)]
    return items[-1] if items else None


def _blocker_text(ctx: AssistantContext) -> str | None:
    blocker = ctx.blocker
    if isinstance(blocker, dict):
        return _text(blocker, "description", "text", "summary", "blocker")
    return blocker.strip() if isinstance(blocker, str) and blocker.strip() else None


def _task_time(task: dict[str, Any]) -> datetime | None:
    return parse_time(task.get("completed_at")) or parse_time(task.get("started_at")) or parse_time(task.get("created_at"))


def _task_summary(task: dict[str, Any]) -> str:
    result = task.get("result") or {}
    return (result.get("summary") if isinstance(result, dict) else None) or task.get("error") or "no summary recorded"


def _doing(ctx: AssistantContext) -> AssistantAnswer:
    obs = _latest_observation(ctx)
    goal = f" Your goal is \"{ctx.goal}\"." if ctx.goal else ""
    if obs is None:
        return AssistantAnswer(f"I haven't recorded any activity for this session yet.{goal}",
                               [f"status: {ctx.status}"] if ctx.status else [])
    activity = _text(obs, "activity", "activity_summary") or "an activity I couldn't describe"
    app = _text(obs, "application", "app_name")
    where = f" in {app}" if app else ""
    when = clock_str(obs.get("timestamp"), ctx.tz)
    alignment = obs.get("goal_alignment")
    fit = ""
    if isinstance(alignment, (int, float)):
        fit = (" That looks aligned with your goal." if alignment >= .6 else
               " That looks only loosely related to your goal." if alignment >= .3 else
               " That doesn't look related to your goal.")
    evidence = [f"observation at {when}: {activity}{where}"]
    if isinstance(alignment, (int, float)):
        evidence.append(f"goal alignment {_pct(alignment)} at {when}")
    phase = _text(obs, "task_phase")
    if phase and phase != "unknown":
        evidence.append(f"task phase: {phase}")
    return AssistantAnswer(f"As of {when} you were {activity[:1].lower() + activity[1:]}{where}.{fit}{goal}", evidence)


def _finished(ctx: AssistantContext) -> AssistantAnswer:
    done = [s for s in ctx.subtasks if s.get("status") == "done"]
    core = [s for s in ctx.segments if s.get("category") == "core_task"]
    evidence: list[str] = []
    lines: list[str] = []
    if ctx.subtasks:
        lines.append(f"{len(done)} of {len(ctx.subtasks)} subtasks are done" + (":" if done else "."))
        for item in done:
            note = (item.get("evidence") or [None])[-1]
            lines.append(f"  - {item.get('title')}")
            evidence.append(f"subtask done: {item.get('title')}" + (f" ({note})" if note else ""))
    if core:
        total = sum(float(s.get("duration_seconds") or 0) for s in core)
        lines.append(f"You spent {fmt_duration(total)} on goal-aligned work across {len(core)} block{'s' if len(core) != 1 else ''}.")
        for seg in core[-3:]:
            label = _text(seg, "activity_summary", "label", "activity") or "focused work"
            evidence.append(f"{clock_str(seg.get('start'), ctx.tz)}-{clock_str(seg.get('end'), ctx.tz)} {label}")
    if ctx.goal_state:
        lines.append(f"Goal state: {ctx.goal_state.replace('_', ' ')}.")
    if not (done or core):
        return AssistantAnswer("I don't have evidence of anything finished yet"
                               + (" (no subtasks are done and no focused blocks are recorded)." if ctx.subtasks or ctx.segments else "."),
                               [f"goal state: {ctx.goal_state}"] if ctx.goal_state else [])
    return AssistantAnswer("\n".join(lines), evidence)


def _score(ctx: AssistantContext) -> AssistantAnswer:
    metrics = ctx.metrics or {}
    score = metrics.get("session_score")
    if score is None:
        return AssistantAnswer("There isn't enough recorded activity to compute a session score yet, so there is nothing to explain.")
    history = [h for h in ctx.score_history if isinstance(h.get("session_score"), (int, float))]
    evidence = [f"current session score {score:.0f}"]
    lines: list[str] = []
    if len(history) >= 2:
        peak = max(history, key=lambda h: h["session_score"])
        drop = peak["session_score"] - score
        if drop > 0.5:
            lines.append(f"Your score is {score:.0f}, down {drop:.0f} from {peak['session_score']:.0f} at {clock_str(peak.get('timestamp'), ctx.tz)}.")
            evidence.append(f"peak score {peak['session_score']:.0f} at {clock_str(peak.get('timestamp'), ctx.tz)}")
        else:
            lines.append(f"Your score is {score:.0f}; I don't see a drop from earlier in the session.")
    else:
        lines.append(f"Your score is {score:.0f}, but I have no earlier score to compare against, so I can't say it dropped.")
    reasons: list[str] = []
    if ctx.drift and str(ctx.drift.get("state", "")).lower() in {"drifting", "sustained_drift"}:
        since = f" since {clock_str(ctx.drift.get('since'), ctx.tz)}" if ctx.drift.get("since") else ""
        reasons.append(f"you are {str(ctx.drift['state']).replace('_', ' ')}{since}")
        evidence.append(f"drift state: {ctx.drift['state']}{since}")
    elif metrics.get("drift_state") in {"drifting", "sustained_drift"}:
        reasons.append(f"you are {str(metrics['drift_state']).replace('_', ' ')}")
        evidence.append(f"drift state: {metrics['drift_state']}")
    distractions = [s for s in ctx.segments if s.get("category") == "distraction"]
    if distractions:
        total = sum(float(s.get("duration_seconds") or 0) for s in distractions)
        names = ", ".join(dict.fromkeys(_text(s, "activity_summary", "label", "activity") or "unrelated activity" for s in distractions[-3:]))
        reasons.append(f"{fmt_duration(total)} went to activity unrelated to the goal ({names})")
        for seg in distractions[-3:]:
            evidence.append(f"{clock_str(seg.get('start'), ctx.tz)}-{clock_str(seg.get('end'), ctx.tz)} distraction: "
                            f"{_text(seg, 'activity_summary', 'label', 'activity') or 'unrelated activity'}")
    switches = metrics.get("context_switches")
    if isinstance(switches, int) and switches >= 5:
        reasons.append(f"{switches} context switches")
        evidence.append(f"context switches: {switches}")
    for key, label in (("goal_alignment", "goal alignment"), ("focus_continuity", "focus continuity"),
                       ("context_stability", "context stability")):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            evidence.append(f"{label} {_pct(value)}")
            if value < .5:
                reasons.append(f"{label} is low ({_pct(value)})")
    blocker = _blocker_text(ctx)
    if blocker:
        reasons.append(f"a possible blocker is flagged: {blocker}")
        evidence.append(f"blocker: {blocker}")
    if reasons:
        lines.append("What the record shows: " + "; ".join(reasons) + ".")
    else:
        lines.append("I don't see a specific cause in the recorded metrics.")
    return AssistantAnswer(" ".join(lines), evidence)


def _next(ctx: AssistantContext) -> AssistantAnswer:
    pending = [r for r in ctx.recommendations if r.get("status", "pending") == "pending"]
    if pending:
        rec = max(pending, key=lambda r: float(r.get("confidence") or 0))
        confidence = f" (confidence {_pct(rec.get('confidence'))})" if rec.get("confidence") is not None else ""
        reason = rec.get("reason") or rec.get("description") or ""
        evidence = [str(e) for e in (rec.get("evidence") or [])]
        text = f"{rec.get('title')}{confidence}." + (f" Why: {reason}" if reason else "")
        if rec.get("can_delegate") and rec.get("proposed_task"):
            text += " FLOW can do this for you: `flow recommend --do`."
        return AssistantAnswer(text, evidence or [f"recommendation {rec.get('id')}"])
    todo = [s for s in ctx.subtasks if s.get("status") in {"in_progress", "todo"}]
    if todo:
        item = sorted(todo, key=lambda s: (s.get("status") != "in_progress", s.get("position", 0)))[0]
        return AssistantAnswer(f"There's no active recommendation. The next unfinished subtask is \"{item.get('title')}\".",
                               [f"subtask {item.get('status')}: {item.get('title')}"])
    if ctx.goal:
        return AssistantAnswer(f"I have no recommendation right now. Your goal is still \"{ctx.goal}\"; "
                               "continue with it, or add subtasks so I can track what's left.", [f"goal: {ctx.goal}"])
    return AssistantAnswer("I have no recommendation to give yet.")


def _blocking(ctx: AssistantContext) -> AssistantAnswer:
    lines: list[str] = []
    evidence: list[str] = []
    blocker = _blocker_text(ctx)
    if blocker:
        lines.append(f"A possible blocker is flagged: {blocker}.")
        evidence.append(f"blocker: {blocker}")
    for approval in (a for a in ctx.approvals if a.get("status", "pending") == "pending"):
        action = approval.get("action") or {}
        what = action.get("summary") or action.get("command") or action.get("tool") or "an action"
        lines.append(f"The agent is waiting for your approval to {what} (risk: {approval.get('risk', 'unknown')}).")
        evidence.append(f"pending approval {approval.get('id')}")
    for task in (t for t in ctx.tasks if t.get("status") == "failed"):
        lines.append(f"A delegated task failed: \"{task.get('instruction')}\" ({task.get('error') or _task_summary(task)}).")
        evidence.append(f"task {task.get('id')} failed")
    if not lines:
        return AssistantAnswer("I don't see anything blocking you in the recorded activity.",
                               [f"status: {ctx.status}"] if ctx.status else [])
    return AssistantAnswer(" ".join(lines), evidence)


def _agent(ctx: AssistantContext) -> AssistantAnswer:
    if not ctx.tasks:
        return AssistantAnswer("The agent hasn't been given any tasks in this session.")
    done = [t for t in ctx.tasks if t.get("status") == "completed"]
    running = [t for t in ctx.tasks if t.get("status") in {"running", "planning", "queued", "waiting_for_approval"}]
    failed = [t for t in ctx.tasks if t.get("status") == "failed"]
    lines: list[str] = []
    evidence: list[str] = []
    for task in done:
        lines.append(f"Completed: \"{task.get('instruction')}\". {_task_summary(task)}")
        result = task.get("result") or {}
        touched = result.get("files_touched") if isinstance(result, dict) else None
        if touched:
            lines.append(f"  Files changed: {', '.join(touched)}")
        evidence.extend(str(e) for e in (task.get("evidence") or (result.get("evidence") if isinstance(result, dict) else []) or [])[:3])
    for task in failed:
        lines.append(f"Failed: \"{task.get('instruction')}\" ({task.get('error') or _task_summary(task)}).")
        evidence.append(f"task {task.get('id')} failed")
    for task in running:
        lines.append(f"In progress: \"{task.get('instruction')}\" ({str(task.get('status')).replace('_', ' ')}).")
    if not (done or failed):
        lines.insert(0, "Nothing has completed yet.")
    return AssistantAnswer("\n".join(lines), evidence)


def _away_periods(ctx: AssistantContext) -> list[dict[str, Any]]:
    return sorted((p for p in ctx.away_periods if parse_time(p.get("start"))), key=lambda p: parse_time(p["start"]))


def _period_end(period: dict[str, Any], now: datetime) -> datetime:
    return parse_time(period.get("end")) or now


def _away_duration(ctx: AssistantContext) -> AssistantAnswer:
    periods = _away_periods(ctx)
    if not periods:
        return AssistantAnswer("I have no record of you being away during this session.")
    last = periods[-1]
    start, end = parse_time(last["start"]), _period_end(last, ctx.now)
    ongoing = parse_time(last.get("end")) is None
    length = fmt_duration((end - start).total_seconds())
    evidence = [f"away from {clock_str(start, ctx.tz)} to {'now' if ongoing else clock_str(end, ctx.tz)}"]
    text = (f"You've been away for {length} (since {clock_str(start, ctx.tz)})." if ongoing
            else f"You were away for {length} ({clock_str(start, ctx.tz)} to {clock_str(end, ctx.tz)}).")
    if len(periods) > 1:
        total = sum((_period_end(p, ctx.now) - parse_time(p["start"])).total_seconds() for p in periods)
        text += f" In total you were away {fmt_duration(total)} across {len(periods)} periods."
        evidence.append(f"{len(periods)} away periods recorded")
    return AssistantAnswer(text, evidence)


_OUTDATED = re.compile(r"\boutdated\b|newer version|latest\s+\S+", re.I)


def _outdated_from(task: dict[str, Any]) -> list[str]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    found: list[str] = []
    for source in (result.get("outdated_packages"), (result.get("facts") or {}).get("outdated")):
        for item in source or []:
            if isinstance(item, dict):
                name = item.get("name") or "?"
                current, latest = item.get("current") or item.get("locked") or item.get("declared"), item.get("latest")
                found.append(f"{name} {current} -> {latest}" if current and latest else str(name))
            else:
                found.append(str(item))
    if not found:
        for line in list(task.get("evidence") or []) + list(result.get("evidence") or []):
            if isinstance(line, str) and _OUTDATED.search(line) and "were not checked" not in line:
                found.append(line)
    return list(dict.fromkeys(found))


def _inspected_packages(task: dict[str, Any]) -> bool:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    return any(step.get("tool") == "inspect_package_metadata" for step in result.get("steps") or []) \
        or "package" in str(task.get("instruction", "")).lower() or "dependenc" in str(task.get("instruction", "")).lower()


def _away_summary(ctx: AssistantContext) -> AssistantAnswer:
    periods = _away_periods(ctx)
    if not periods:
        return AssistantAnswer("I have no record of you being away, so there's no return summary to give.")
    period = periods[-1]
    start, end = parse_time(period["start"]), _period_end(period, ctx.now)
    ongoing = parse_time(period.get("end")) is None
    length = fmt_duration((end - start).total_seconds())
    evidence = [f"away from {clock_str(start, ctx.tz)} to {'now' if ongoing else clock_str(end, ctx.tz)}"]
    lines = [(f"You've been away for {length} (since {clock_str(start, ctx.tz)})." if ongoing
              else f"You were away for {length} ({clock_str(start, ctx.tz)} to {clock_str(end, ctx.tz)}).")]

    done = [t for t in ctx.tasks if t.get("status") == "completed" and (when := _task_time(t)) and start <= when <= end]
    if done:
        lines.append(f"{len(done)} delegated task{'s' if len(done) != 1 else ''} completed while you were away:")
        for task in done:
            lines.append(f"  - {task.get('instruction')}: {_task_summary(task)}")
            evidence.append(f"task {task.get('id')} completed at {clock_str(_task_time(task), ctx.tz)}")
    else:
        lines.append("No delegated tasks completed while you were away.")

    touched: list[str] = []
    for task in done:
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        touched.extend(result.get("files_touched") or [])
    touched = list(dict.fromkeys(touched))
    if touched:
        lines.append(f"Files modified by the agent: {', '.join(touched)}.")
        evidence.append(f"files touched: {', '.join(touched)}")
    else:
        lines.append("No files were modified by delegated tasks.")

    outdated: list[str] = []
    inspected = False
    for task in done:
        outdated.extend(_outdated_from(task))
        inspected = inspected or _inspected_packages(task)
    outdated = list(dict.fromkeys(outdated))
    if outdated:
        lines.append(f"Outdated packages found: {', '.join(outdated[:8])}" + (f" (+{len(outdated) - 8} more)." if len(outdated) > 8 else "."))
        evidence.extend(f"outdated: {item}" for item in outdated[:8])
    elif inspected:
        lines.append("A dependency check ran, but it did not report any outdated packages "
                     "(it compares declared and locked versions and does not look up newer releases).")
    else:
        lines.append("No dependency check ran, so I have no outdated-package information.")

    paused = period.get("analysis_paused")
    if paused is True:
        lines.append("Screen analysis was paused while you were away.")
    elif paused is False:
        lines.append("Screen analysis kept running while you were away.")
        during = [o for o in ctx.observations if (t := parse_time(o.get("timestamp"))) and start <= t <= end]
        if during:
            evidence.append(f"{len(during)} observation(s) recorded while away")
    else:
        lines.append("I don't have a record of whether analysis was paused while you were away.")
    evidence.append(f"analysis_paused: {paused if paused is not None else 'unknown'}")
    return AssistantAnswer("\n".join(lines), evidence)


_HANDLERS = {"doing": _doing, "finished": _finished, "score": _score, "next": _next, "blocker": _blocking,
             "agent": _agent, "away_duration": _away_duration, "away_summary": _away_summary}

__all__ = ["AssistantAnswer", "AssistantContext", "SUPPORTED_QUESTIONS", "answer", "classify", "clock_str",
           "fmt_duration", "parse_time"]
