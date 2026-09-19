/**
 * Temporal reasoning: turn discrete, possibly-missing observation samples into
 * explicit time intervals with honest boundaries.
 *
 * Design rule: a missing observation is never evidence that the previous activity
 * continued. Each sample may only "hold" the screen for `samplePeriodMs` (plus a
 * small grace factor). Anything beyond that becomes an explicit `unobserved` gap
 * that is reported rather than silently attributed to the last known category.
 */

export const DEFAULT_SAMPLE_PERIOD_MS = 5000;
/** A sample may extend at most this multiple of the sample period before we call it a gap. */
export const GAP_GRACE_FACTOR = 2.5;

const ms = (t) => new Date(t).getTime();
const iso = (n) => new Date(n).toISOString();

/** Merge overlapping [start,end) windows, dropping zero/negative spans. */
function normaliseWindows(windows) {
  const valid = windows
    .map((w) => [ms(w.startedAt), w.endedAt ? ms(w.endedAt) : Infinity])
    .filter(([a, b]) => Number.isFinite(a) && b > a)
    .sort((x, y) => x[0] - y[0]);
  const out = [];
  for (const [a, b] of valid) {
    const last = out[out.length - 1];
    if (last && a <= last[1]) last[1] = Math.max(last[1], b);
    else out.push([a, b]);
  }
  return out;
}

/** Subtract `windows` from [start,end), returning the surviving spans. */
function subtractWindows(start, end, windows) {
  let spans = [[start, end]];
  for (const [a, b] of windows) {
    const next = [];
    for (const [s, e] of spans) {
      if (b <= s || a >= e) { next.push([s, e]); continue; }
      if (a > s) next.push([s, a]);
      if (b < e) next.push([b, e]);
    }
    spans = next;
  }
  return spans.filter(([s, e]) => e > s);
}

/**
 * Build the interval timeline for a session.
 *
 * @param {object} session
 * @param {object} [options]
 * @param {number} [options.now] epoch ms used to bound a still-running session
 * @returns {{intervals: Array, pausedMs: number, unobservedMs: number, observedMs: number, coverage: number|null, boundedAt: string}}
 */
export function buildIntervals(session, options = {}) {
  const now = options.now ?? Date.now();
  const samplePeriodMs = session.samplePeriodMs || DEFAULT_SAMPLE_PERIOD_MS;
  const maxHoldMs = samplePeriodMs * GAP_GRACE_FACTOR;

  const sessionStart = ms(session.startedAt);
  const sessionEnd = session.endedAt ? ms(session.endedAt) : Math.max(now, sessionStart);
  const pauses = normaliseWindows(session.pauses || []).map(([a, b]) => [a, Math.min(b, sessionEnd)]);

  // De-duplicate by event id, then by (time, app, title) for producers that retry.
  const seenIds = new Set();
  const seenKeys = new Set();
  const samples = [];
  for (const e of session.events || []) {
    if (e.type !== 'observation.created') continue;
    if (e.id && seenIds.has(e.id)) continue;
    const t = ms(e.time);
    if (!Number.isFinite(t)) continue;
    const key = `${t}|${e.app}|${e.title}`;
    if (seenKeys.has(key)) continue;
    if (e.id) seenIds.add(e.id);
    seenKeys.add(key);
    samples.push({ ...e, _t: Math.min(Math.max(t, sessionStart), sessionEnd) });
  }
  samples.sort((a, b) => a._t - b._t || String(a.id).localeCompare(String(b.id)));

  const raw = [];
  for (let i = 0; i < samples.length; i += 1) {
    const s = samples[i];
    const nextT = i + 1 < samples.length ? samples[i + 1]._t : sessionEnd;
    // Hold the observation until the next sample, but never longer than the grace window.
    const end = Math.min(nextT, s._t + maxHoldMs, sessionEnd);
    if (end <= s._t) continue;
    raw.push({ sample: s, start: s._t, end });
  }

  // Coalesce consecutive, contiguous samples that describe the same activity.
  const merged = [];
  for (const seg of raw) {
    const prev = merged[merged.length - 1];
    const s = seg.sample;
    const sameActivity =
      prev &&
      prev.app === s.app &&
      prev.category === s.category &&
      (prev.taskContext || null) === (s.taskContext || null) &&
      Math.abs(prev._end - seg.start) < 1;
    if (sameActivity) {
      prev._end = seg.end;
      prev.sampleCount += 1;
      prev.observationIds.push(s.id);
      if (s.title && !prev.titles.includes(s.title)) prev.titles.push(s.title);
      // Keep the most recent interpretation, but retain the highest confidence seen.
      prev.explanation = s.reason ?? prev.explanation;
      prev.confidence = Math.max(prev.confidence, s.confidence ?? 0);
      if (s.goalRelevance !== null && s.goalRelevance !== undefined) prev.goalRelevance = s.goalRelevance;
      for (const ev of s.evidence || []) if (!prev.evidence.includes(ev)) prev.evidence.push(ev);
      if (s.progressSignal && !prev.progressSignals.includes(s.progressSignal)) prev.progressSignals.push(s.progressSignal);
    } else {
      merged.push({
        id: `int_${s.id}`,
        app: s.app,
        title: s.title || '',
        titles: s.title ? [s.title] : [],
        category: s.category,
        taskContext: s.taskContext || null,
        goalRelevance: s.goalRelevance ?? null,
        confidence: s.confidence ?? 0,
        explanation: s.reason || '',
        evidence: [...(s.evidence || [])],
        progressSignals: s.progressSignal ? [s.progressSignal] : [],
        analysis: s.analysis || null,
        simulated: !!s.simulated,
        screenshotRetention: s.analysis?.screenshotRetention || 'not-captured',
        observationIds: [s.id],
        sampleCount: 1,
        _start: seg.start,
        _end: seg.end,
      });
    }
  }

  // Clip out paused time, then emit final intervals.
  const intervals = [];
  for (const m of merged) {
    for (const [s, e] of subtractWindows(m._start, m._end, pauses)) {
      intervals.push({
        ...m,
        id: intervals.some((x) => x.id === m.id) ? `${m.id}_${intervals.length}` : m.id,
        startedAt: iso(s),
        endedAt: iso(e),
        durationMs: e - s,
        _start: undefined,
        _end: undefined,
      });
    }
  }

  // Fill everything the observer did not cover: gaps, head, tail — minus pauses.
  const covered = normaliseWindows(intervals);
  const holes = subtractWindows(sessionStart, sessionEnd, normaliseWindows([...intervals, ...pauses.map(([a, b]) => ({ startedAt: iso(a), endedAt: iso(b) }))]));
  for (const [s, e] of holes) {
    if (e - s < 1000) continue; // ignore sub-second scheduling jitter
    intervals.push({
      id: `gap_${s}`,
      app: null,
      title: '',
      titles: [],
      category: 'unobserved',
      taskContext: null,
      goalRelevance: null,
      confidence: 0,
      explanation: 'No observation was recorded in this window. FLOW does not assume the previous activity continued.',
      evidence: [],
      progressSignals: [],
      analysis: null,
      simulated: false,
      screenshotRetention: 'not-captured',
      observationIds: [],
      sampleCount: 0,
      startedAt: iso(s),
      endedAt: iso(e),
      durationMs: e - s,
    });
  }
  for (const [s, e] of pauses) {
    if (e - s < 1000) continue;
    intervals.push({
      id: `pause_${s}`,
      app: null,
      title: '',
      titles: [],
      category: 'paused',
      taskContext: null,
      goalRelevance: null,
      confidence: 0,
      explanation: 'Session paused. Observation and analysis were stopped.',
      evidence: [],
      progressSignals: [],
      analysis: null,
      simulated: false,
      screenshotRetention: 'not-captured',
      observationIds: [],
      sampleCount: 0,
      startedAt: iso(s),
      endedAt: iso(Math.min(e, sessionEnd)),
      durationMs: Math.min(e, sessionEnd) - s,
    });
  }

  intervals.sort((a, b) => ms(a.startedAt) - ms(b.startedAt));

  const pausedMs = intervals.filter((i) => i.category === 'paused').reduce((n, i) => n + i.durationMs, 0);
  const unobservedMs = intervals.filter((i) => i.category === 'unobserved').reduce((n, i) => n + i.durationMs, 0);
  const observedMs = intervals.filter((i) => i.category !== 'paused' && i.category !== 'unobserved').reduce((n, i) => n + i.durationMs, 0);
  const observable = observedMs + unobservedMs;

  void covered;
  return {
    intervals,
    pausedMs,
    unobservedMs,
    observedMs,
    coverage: observable > 0 ? observedMs / observable : null,
    boundedAt: iso(sessionEnd),
    samplePeriodMs,
  };
}
