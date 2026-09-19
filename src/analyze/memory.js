/**
 * Compact, persistent session memory.
 *
 * Without this, every inference call would re-analyze a screenshot from scratch
 * with no idea what the session has been doing. Memory gives the analyzer
 * continuity (so a return to work can be recognised as *recovery*) while staying
 * small enough to send on every call — it is a rolling summary plus bounded
 * lists, never the full event log, and it never stores raw screenshots.
 */

const MAX_RECENT = 12;
const MAX_CONTEXTS = 16;
const MAX_TRANSITIONS = 40;

export function blankMemory() {
  return {
    schema: 'flow.memory.v2',
    summary: '',
    taskContexts: [],
    transitions: [],
    recent: [],
    lastCategory: null,
    lastAwayAt: null,
    lastProgressAt: null,
    progressSignals: [],
    observationCount: 0,
    updatedAt: null,
  };
}

/**
 * Fold one classified observation into memory.
 * Mutates and returns `memory` (callers persist it with the session).
 */
export function rememberObservation(memory, { observation, classification }) {
  const mem = memory && memory.schema === 'flow.memory.v2' ? memory : blankMemory();
  const time = observation.time;
  const category = classification.category;

  mem.observationCount += 1;
  mem.updatedAt = time;

  mem.recent.push({
    time,
    app: observation.app,
    title: observation.title,
    category,
    confidence: classification.confidence,
    goalRelevance: classification.goalRelevance ?? null,
  });
  if (mem.recent.length > MAX_RECENT) mem.recent.splice(0, mem.recent.length - MAX_RECENT);

  const contextName = classification.taskContext || `${observation.app}`;
  let ctx = mem.taskContexts.find((c) => c.name === contextName);
  if (!ctx) {
    ctx = { name: contextName, category, firstSeen: time, lastSeen: time, sampleCount: 0 };
    mem.taskContexts.push(ctx);
    if (mem.taskContexts.length > MAX_CONTEXTS) mem.taskContexts.shift();
  }
  ctx.lastSeen = time;
  ctx.category = category;
  ctx.sampleCount += 1;

  if (mem.lastCategory && mem.lastCategory !== category) {
    mem.transitions.push({ at: time, from: mem.lastCategory, to: category });
    if (mem.transitions.length > MAX_TRANSITIONS) mem.transitions.shift();
  }
  mem.lastCategory = category;

  if (category === 'drift' || category === 'distraction') mem.lastAwayAt = time;
  else if (category === 'core' || category === 'supporting' || category === 'recovery') mem.lastAwayAt = null;

  if (classification.progressSignal) {
    mem.lastProgressAt = time;
    mem.progressSignals.push({ at: time, text: classification.progressSignal });
    if (mem.progressSignals.length > MAX_RECENT) mem.progressSignals.shift();
  }

  mem.summary = summarise(mem);
  return mem;
}

/**
 * Deterministic rolling summary.
 *
 * Deliberately generated from counted facts rather than by a model: it is cheap,
 * reproducible, and cannot hallucinate a narrative about the session.
 */
export function summarise(memory) {
  if (!memory.observationCount) return '';
  const counts = {};
  for (const r of memory.recent) counts[r.category] = (counts[r.category] || 0) + 1;

  const contexts = memory.taskContexts
    .slice()
    .sort((a, b) => b.sampleCount - a.sampleCount)
    .slice(0, 3)
    .map((c) => c.name);

  const bits = [`${memory.observationCount} observation(s) so far.`];
  if (contexts.length) bits.push(`Main task contexts: ${contexts.join(', ')}.`);
  const recentShape = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => `${k}×${v}`)
    .join(', ');
  if (recentShape) bits.push(`Recent window: ${recentShape}.`);
  const flips = memory.transitions.slice(-3).map((t) => `${t.from}→${t.to}`);
  if (flips.length) bits.push(`Latest transitions: ${flips.join(', ')}.`);
  if (memory.lastProgressAt) bits.push(`Last observed progress signal at ${memory.lastProgressAt}.`);
  if (memory.lastAwayAt) bits.push(`Currently away from the goal since ${memory.lastAwayAt}.`);
  return bits.join(' ');
}

/** The slice of memory handed to a provider, kept deliberately small. */
export function memoryForPrompt(memory) {
  const mem = memory || blankMemory();
  return {
    summary: mem.summary,
    taskContexts: mem.taskContexts,
    lastAwayAt: mem.lastAwayAt,
  };
}
