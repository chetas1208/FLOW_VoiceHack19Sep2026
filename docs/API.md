# FLOW HTTP API (v2)

Base URL `http://127.0.0.1:8080`. All responses are JSON. Errors are `{ "error": string, "issues"?: [...] }`
with a meaningful status code. Live JSON fixtures for every shape below are in `docs/fixtures/`.

## Meta & configuration

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/meta` | Platform, OS permission states, analyzer status, voice availability, category legend, stream seq. |
| `GET` | `/api/voices` | Installed English TTS voices (`[{name, locale, sample}]`). |
| `POST` | `/api/permissions/screen-recording` | Triggers the macOS Screen Recording prompt once. |
| `POST` | `/api/analyzer/probe` | Re-probes analyzer providers, returns the new status. |
| `GET`/`POST` | `/api/settings` | Global defaults for new sessions (`privacy`, `voice`, `observer`, `analyzer`). |
| `DELETE` | `/api/data` | **Destructive.** Deletes every session. Returns `{deletedSessions, verified}`. |

## Sessions

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/sessions?q=&status=` | Summary rows (no event log). Filter by substring and status. |
| `POST` | `/api/sessions` | `{goal, observe?, screenshots?, voice?, simulated?}` → full session, 201. |
| `GET` | `/api/sessions/:id` | Full session including `events`, `memory`, `coach`, `metrics`. |
| `DELETE` | `/api/sessions/:id` | Returns `{deleted, verified}` — `verified` is re-read from the store. |
| `GET` | `/api/sessions/:id/report` | Full report (see `docs/fixtures/report.json`). |
| `GET` | `/api/sessions/:id/evidence` | Intervals + per-interval observations + intervention outcomes. |
| `GET` | `/api/sessions/:id/timeline` | Raw interval build: `{intervals, observedMs, unobservedMs, coverage}`. |
| `GET` | `/api/sessions/:id/export` | JSON download (`Content-Disposition: attachment`). |

### Session actions (all `POST /api/sessions/:id/<action>`)

| Action | Body | Effect |
|---|---|---|
| `observe` | `{app, title?, time?, simulated?}` | Runs the full pipeline. May return `{excluded:true}` or `{duplicate:true}`. |
| `pause` / `resume` / `stop` | — | Lifecycle. `stop` also generates the report. |
| `capture` | `{enabled?, screenshots?}` | Toggles the OS observer / screenshot capture. |
| `privacy` | `{excludedApps?, screenshotsEnabled?, retention?, retentionMinutes?, analysisLocation?, cloudConsent?}` | Selecting `cloud` without `cloudConsent` is reverted to `metadata-only` and returns a `warning`. |
| `voice` | `{enabled?, voice?, rate?, cooldownMinutes?, sustainedDriftSeconds?, minConfidence?}` | Voice settings. |
| `mute` / `unmute` | `{minutes?}` | Mute the coach. |
| `outcome` | `{outcome}` | One of `completed`, `partial`, `not-completed`, `prefer-not-to-say`. Session must be stopped. |
| `interventions/:interventionId` | `{action:"dismiss", note?}` | Dismiss an intervention. |
| `recompute` | — | Recompute metrics. |

## Event stream

`GET /api/events` — Server-Sent Events. Each message has an `id` (global sequence), an `event:` name
and a JSON `data` payload `{seq, type, sessionId?, session?, event?, intervention?, ...}`.

Reconnect with `Last-Event-ID` (the browser's `EventSource` does this automatically) or `?since=N` to
replay missed events from a 500-entry ring buffer. On connect the server sends either
`stream.connected` (`{seq, gap, resnapshot}`) or `stream.resumed` (`{from, replaying, seq}`).
**If `resnapshot` is true, re-fetch the session snapshot — the gap is unrecoverable.**

Event types: `session.started|paused|resumed|stopped|deleted`, `observation.created`, `metrics.updated`,
`drift.changed`, `intervention.triggered|queued|speech_started|speech_completed|failed|muted|dismissed|updated`,
`analyzer.status`, `observer.status`, `privacy.changed`, `voice.changed`, `report.updated`,
`settings.changed`, `data.deleted`.

## Key object shapes

**Observation event** (`session.events[]` where `type === 'observation.created'`):
`{id, seq, time, app, title, titleWithheld, redactions[], simulated, category, goalRelevance|null,
confidence, confidenceCalibrated, evidence[], reason, taskContext|null, progressSignal|null, analysis}`

`analysis` = `{provider, model|null, modality: 'metadata-only'|'vision-language'|'text-language',
latencyMs, usedScreenshot, screenshotRetention: 'not-captured'|'discarded-after-analysis'|'retained',
degraded, note}`

**Interval** (`metrics.timeline[]`, `evidence.intervals[]`):
`{id, startedAt, endedAt, durationMs, app|null, title, titles[], category, taskContext, goalRelevance,
confidence, explanation, evidence[], progressSignals[], analysis, simulated, screenshotRetention,
observationIds[], sampleCount}` — `category` may additionally be `'unobserved'` or `'paused'`.

**Metrics** (`session.metrics`, `report.metrics`): `{goalAlignment, focusContinuity, contextStability,
progressSignal, sessionScore, band, confidence, uncertainty, coverage, durationsMs{}, shares{},
focus{blockThresholdMs, blockCount, longestBlockMs, medianBlockMs, blocks[]}, contextSwitches,
switchDensityPerHour, switchPoints[], progressSignals[], method{}, timeline[]}`.
**Every numeric metric may be `null`** when there is no evidence — render "No data", never `0`.

**Coach** (`session.coach`): `{state: 'FOCUSED'|'WATCHING'|'DRIFT_CANDIDATE'|'INTERVENE'|'RECOVERY'|'COOLDOWN',
since, driftSince, cooldownUntil, muteUntil, lastInterventionAt, interventionCount, suppressedReason}`

**Intervention**: `{id, triggeredAt, stage, transcript, reason, observationId, evidence[], driftSeconds,
confidence, dismissed, lifecycle:[{stage, at, ...}], outcome}` where `outcome` (report/evidence only) is
`{before, after, alignedShareDelta, returnedToGoal, observation, caveat}`.
