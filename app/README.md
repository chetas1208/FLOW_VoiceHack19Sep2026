# FLOW — local session intelligence MVP

A working, zero-dependency Node.js dashboard and CLI built from the supplied 11-page FLOW UI/UX specification. The product includes a dark cockpit, live server-sent events, local session persistence, activity timeline, classifications with evidence, report, privacy controls, optional macOS frontmost-app metadata observation, and optional macOS spoken interventions.

## Run

Requires Node.js 20+. No `npm install` is needed.

```bash
npm start
# Open http://127.0.0.1:8080
```

In another terminal:

```bash
npm run cli -- start "Fix JWT authentication and get the failing tests passing"
npm run cli -- list
npm run cli -- observe SESSION_ID "VS Code" "auth/middleware.ts — JWT tests"
npm run cli -- observe SESSION_ID "Chrome" "JWT expiration documentation"
npm run cli -- pause SESSION_ID
npm run cli -- resume SESSION_ID
npm run cli -- stop SESSION_ID
npm run cli -- report SESSION_ID
```

Or click **Create demo session** in the web UI, or use `npm run cli -- demo`. Demo observations are explicitly **simulated**, not collected from your screen. Start a session through the web UI to use manual mode.

### Optional metadata observation (macOS only)

```bash
npm run cli -- start "Fix JWT authentication" --observe
```

`--observe` explicitly opts into polling the frontmost application and window title every 5 seconds using macOS System Events / AppleScript. The OS may ask for Accessibility permissions for Terminal or the Node process. If permissions are unavailable, the app disables automatic observation and shows an error instead of fabricating data. No screenshots, browser content, or microphone data are collected. Window titles can themselves contain private data: review/exclude apps in Privacy, or pause observation whenever needed.

### Optional voice coaching

```bash
npm run cli -- voice SESSION_ID on
npm run cli -- mute SESSION_ID 15
```

Voice is **off by default**. On macOS, coaching uses the local `say` command. It is triggered only after 90 seconds of high-confidence classified drift, and is subject to a 15-minute cooldown. Current metadata-only observation cannot establish true attention or intent, and so intervention should be treated as tentative. On non-macOS platforms, voice events can be recorded but audible speech is not implemented.

### Configuration

- `PORT=8080` — loopback-only HTTP port (binds `127.0.0.1`).
- `FLOW_URL=http://127.0.0.1:8080` — CLI API endpoint.
- `FLOW_DATA_FILE=/custom/path/sessions.json` — persistent session data path.
- Data is written to `data/sessions.json` with mode `0600`; to delete persisted data, stop the server and remove this file.
- Exclusions: 1Password, Messages, Keychain Access and System Settings by default; edit the current session's list via `/settings/privacy`.

## Run tests

```bash
npm test
```

## Architecture

- `src/server.js` — loopback HTTP, REST, SSE, macOS metadata observer, local JSON storage.
- `src/core.js` — pure-ish classification, session metrics, evidence, report, intervention logic.
- `src/cli.js` — start, list, observe, pause/resume/stop, voice, mute, report, simulated demo.
- `public/` — responsive standalone HTML/CSS/JS SPA; routes `/sessions`, `/session/:id/live`, `/session/:id/report`, `/session/:id/evidence`, `/settings/privacy`.
- `tests/` — Node built-in test runner tests.

## Honest scope and known limitations

This is a functional **local prototype**, not a complete AI screen-understanding product. It uses transparent app/title keyword heuristics; it has no vision model, screen capture, cloud inference, user accounts, synchronized multi-device storage, production authentication, or validated psychometric measurements. It deliberately avoids claiming precise time spent in each activity: observations may be irregular and only sample counts are measured. Session score and focus/context values are illustrative unvalidated heuristics, not statements about productivity or attention. It cannot automatically confirm that a coding task is completed. Voice is macOS-only, and browser UI must be open to display the intervention pill. Browser / CLI manual input records the data you give it. Do not expose this unauthenticated loopback server through port forwarding or a public proxy.

## How to evolve toward the full specification

1. Replace the `classify` heuristic with an opt-in semantic analyzer using on-device inference or a documented provider, including calibrated confidence and a privacy-safe capture pipeline. If adding screen capture, enforce macOS user permission and screenshot deletion immediately after analysis.
2. Add timed observation interval events, correct transition boundaries, and duration-based reports without guessing durations from sparse observations.
3. Introduce a properly validated scoring contract, with uncertainty bands and evidence-linked explanations.
4. Add session delete/export UI, per-session exclusion persistence policy, and more robust database storage.
5. Add separate voice-event delivery states, completion timestamps, and real before/after intervention analysis, plus a dedicated accessibility audit.
6. If the project grows, migrate the web frontend to Next.js/React + TypeScript as in the spec; this zero-dependency implementation was chosen so the MVP runs immediately offline.
