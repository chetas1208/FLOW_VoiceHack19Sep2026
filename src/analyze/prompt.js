/**
 * Prompt construction for the semantic analyzer.
 *
 * The prompt encodes the product's central judgement call: relevance is decided
 * against the *stated goal*, not against a blocklist of "bad" apps. Reading
 * YouTube's engineering blog while researching recommendation algorithms is
 * research; reading it while fixing a JWT bug is drift.
 */

export const CATEGORY_GUIDE = `
- core        : Directly advancing the stated goal (editing the relevant code, running its tests, debugging it).
- supporting  : Genuinely serving the goal without being the goal itself — reading documentation or specs for the
                technology in question, searching an error message from this task, reviewing a related PR, asking a
                colleague about this task. Research that is ON-TOPIC for the goal belongs here, whatever app it is in.
- unknown     : Evidence is insufficient to judge. Use this freely. A blank window title, a generic app name, an
                untitled document or an ambiguous page is unknown — NOT distraction.
- drifting    : Plausibly-work activity that has wandered off the stated goal (a different project's code, unrelated
                tickets, general inbox triage) — weak goal relevance, but not obviously recreational.
- distraction : High-confidence unrelated activity with no visible link to the goal (recreational video, social feeds,
                shopping, gaming). Requires clear evidence, not just the app's reputation.
- recovery    : The first activity that returns to core/supporting work after a period of drifting or distraction.
`.trim();

export const SYSTEM_PROMPT = `You are the semantic analyzer inside FLOW, a privacy-first work-session tool.

You receive: the user's stated session goal, a description of what is on screen right now (application name, window
title, and optionally a screenshot), a compact memory of the session so far, and the immediately preceding activity.
You decide how the current activity relates to the stated goal.

Categories:
${CATEGORY_GUIDE}

Rules you must follow:
1. Judge relevance against the STATED GOAL, not against whether an app is stereotypically "productive".
   A YouTube page can be core research; an IDE can be drift if it is a different project.
2. Prefer "unknown" over guessing. Low-evidence situations must be reported as unknown with low confidence, and you
   must NOT invent a rationale to justify a confident-sounding label.
3. "evidence" must contain only things you can actually observe in the input (app name, literal title text, things
   visible in the screenshot). Never put inference in the evidence list — inference belongs in "explanation".
4. Developers legitimately move between code, documentation, terminals, tests, version control and task-related chat.
   Do not treat that movement as drift.
5. Never infer, describe or speculate about the person's mood, motivation, health, intelligence, character or attention.
   You classify ACTIVITY relative to a GOAL. Nothing else.
6. "confidence" is your honest, uncalibrated estimate that the category is right given the evidence. It is not a
   probability derived from data. Be conservative.
7. Set "progressSignal" only when the screen shows concrete evidence the goal moved forward — a passing test run, a
   commit, a closed issue, a resolved error. Otherwise leave it null. Absence of a signal is not evidence of no progress.

Respond only with the structured object requested.`;

const line = (label, value) => (value ? `${label}: ${value}` : null);

/** Build the user-visible portion of the prompt. Returns a plain-text block. */
export function buildUserPrompt({ goal, observation, memory, recent = [] }) {
  const parts = [];
  parts.push(`STATED SESSION GOAL\n${goal}`);

  const obsLines = [
    line('Application', observation.app),
    observation.titleWithheld
      ? 'Window title: withheld — this window looked like a private context, so its title was not recorded.'
      : line('Window title', observation.title || '(empty)'),
    observation.redactions?.length ? `Redactions applied to the title: ${observation.redactions.join(', ')}` : null,
    line('Observed at', observation.time),
    observation.screenshotAllowed ? 'A screenshot of this moment is attached.' : 'No screenshot is available; judge from metadata only.',
  ].filter(Boolean);
  parts.push(`CURRENT OBSERVATION\n${obsLines.join('\n')}`);

  if (memory?.summary) parts.push(`SESSION MEMORY (compact summary of the session so far)\n${memory.summary}`);

  if (memory?.taskContexts?.length) {
    const ctx = memory.taskContexts
      .slice(-6)
      .map((c) => `- ${c.name} (${c.category}, seen ${c.sampleCount}×, last ${c.lastSeen})`)
      .join('\n');
    parts.push(`KNOWN TASK CONTEXTS IN THIS SESSION\n${ctx}`);
  }

  if (recent.length) {
    const rows = recent
      .slice(-6)
      .map((r) => `- ${r.time} · ${r.app} · "${r.title || ''}" → ${r.category} (${Math.round((r.confidence || 0) * 100)}%)`)
      .join('\n');
    parts.push(`RECENT ACTIVITY (most recent last)\n${rows}`);
  }

  if (memory?.lastAwayAt) {
    parts.push(
      `NOTE: the user was last classified as drifting/distracted at ${memory.lastAwayAt}. If the current activity is core or supporting work, classify it as "recovery" instead.`,
    );
  }

  parts.push('Classify the CURRENT OBSERVATION relative to the STATED SESSION GOAL.');
  return parts.join('\n\n');
}

/** JSON Schema handed to providers that support constrained decoding. */
export const CLASSIFICATION_JSON_SCHEMA = {
  type: 'object',
  properties: {
    category: { type: 'string', enum: ['core', 'supporting', 'unknown', 'drift', 'distraction', 'recovery'] },
    goalRelevance: { type: 'number', description: '0 = unrelated to the goal, 1 = directly advancing it.' },
    confidence: { type: 'number', description: 'Honest uncalibrated confidence that the category is correct, 0-1.' },
    evidence: {
      type: 'array',
      items: { type: 'string' },
      description: 'Only directly observable facts (app name, literal title text, what is visible in the screenshot).',
    },
    explanation: { type: 'string', description: 'One or two sentences connecting the evidence to the goal.' },
    taskContext: { type: ['string', 'null'], description: 'Short label for the kind of work, e.g. "auth middleware" or "jwt docs".' },
    progressSignal: { type: ['string', 'null'], description: 'Concrete evidence the goal moved forward, else null.' },
  },
  required: ['category', 'goalRelevance', 'confidence', 'evidence', 'explanation', 'taskContext', 'progressSignal'],
  additionalProperties: false,
};
