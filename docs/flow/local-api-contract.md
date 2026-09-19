# FLOW local API contract (v1)

The **daemon on the user's Mac is the only backend**. It serves this API on `127.0.0.1:8765` (never `0.0.0.0`
unless explicitly configured). Remote access is *transport only*: Tailscale Serve proxies
`https://<mac>.<tailnet>.ts.net` -> `http://127.0.0.1:8765` (opt-in Funnel for public). There is no FLOW cloud, no hosted DB,
no account. The web app (`web/`, deployed static on Vercel **and** embedded in the wheel and served by the daemon at `/ui`)
talks to this API directly from the browser. Shared models: `services/flow/remote_models.py` (entity JSON = `to_dict()`).
Local source of truth: SQLite on the Mac. Server code: `services/flow/server/`.

## Conventions
JSON only; ISO-8601 UTC times; errors `{"error": code, "message"}` with codes `unauthorized`(401) `forbidden`(403) `not_found`(404)
`conflict`(409) `validation_error`(422) `payload_too_large`(413) `rate_limited`(429). Responses carry `X-Request-ID`.
CORS: exact-origin echo only for allowed origins (`FLOW_ALLOWED_ORIGINS`, default `https://app.flow.ai` + `http://localhost:5173`
+ the daemon's own origin); never `*` on privileged routes. Every privileged request also validates `Origin` when present.
Body limits 64 KB (1 MB for report/batch). Rate limits on pairing, auth, command creation.

## Pairing and authentication (no accounts)
The daemon has a long-term Ed25519 identity (fingerprint = SHA-256 of the public key, shown in `flow remote pair` and pinned by the browser).
Browsers create an ECDSA P-256 keypair with WebCrypto (non-extractable, kept in IndexedDB). The daemon stores only the client public key.

* `GET /v1/health` (public) -> `{"status":"ok","version","name","fingerprint","time"}`.
* `POST /v1/pair` (public, strict rate limit) `{"code"|"token","client_name","public_key":"<base64 SPKI>"}` ->
  `{"client_id","daemon_fingerprint","daemon_name"}`. The one-time pairing secret (5 min, single use, max 5 wrong attempts; short code
  `H7KM-92QP` for private mode, long 256-bit key required in public/Funnel mode) is destroyed on success.
  Pairing URL/QR: `https://app.flow.ai/pair#e=<endpoint>&f=<fingerprint>&t=<token>` (fragment, never sent to a server).
* `POST /v1/auth/challenge` `{"client_id"}` -> `{"nonce","expires_in":60}`.
* `POST /v1/auth/verify` `{"client_id","nonce","signature":"<base64 ECDSA-P256-SHA256 over utf8(\"flow-auth-v1|\"+nonce+\"|\"+client_id+\"|\"+origin)>"}`
  -> `{"access_token","expires_in":600}` (daemon-signed JWT, `cid` claim). Nonces are single use (replay -> 401). The browser re-authenticates
  silently every ~9 min. Revoked client: challenge/verify/any request -> 401 immediately; open sockets are closed with 4401.
* Everything below needs `Authorization: Bearer <access_token>` (or the WS first-frame auth). Never a query-string token.
* `GET /v1/me` -> `{"client_id","name","created_at"}`. `GET /v1/clients`, `DELETE /v1/clients/{id}` (revoke; also `flow remote revoke`).

## Reads
* `GET /v1/status` -> `{"daemon":{version,uptime,pid},"models":{intelligence:{name,size,backend,state,memory_mb,latency_ms},voice:{...}},
  "observer":{...},"voice":{"state","muted_until"},"remote":{mode,endpoint,status},"active_sessions":[ids],"health":{...}}` (this is the "device presence").
* `GET /v1/sessions?status=&limit=&cursor=` -> `{"items":[SessionOut],"next_cursor"}`; SessionOut `{"id","goal","status"(RuntimeStatus),"started_at","ended_at","updated_at","goal_version","runtime_state","workspace"}`.
* `GET /v1/sessions/{id}` -> `{"session","summary"|null,"metrics","segments","interventions","goal_history","subtasks"}`.
* `GET /v1/sessions/{id}/live` -> `{"session","daemon":{...status health...},"current":{activity,task_phase,alignment,drift,blocker,category,application},
  "metrics","efficiency","latest_segment","observer_health","voice","agent":{status,current_task,pending_approvals},
  "human":{...},"goal":{text,version,state,subtasks,history},"recommendation"|null,"tasks":[last 20],"approvals":[pending],"last_event_sequence"}`.
* `GET /v1/sessions/{id}/report` -> full local report (goal versions, durations, alignment, focus, stability, progress, coverage, confidence, segments,
  blockers, drift, recommendations, voice interventions, human vs agent activity, tasks, approvals, results).
* `GET /v1/sessions/{id}/observations?after_sequence=&limit=`, `.../events?after=&limit=`, `.../entities?kind=&status=`, `.../commands`.
  Entity kinds: `task approval recommendation subtask goal_version chat runtime_state`.
* `GET /v1/approvals?status=pending` (all sessions), `GET /v1/tasks/{id}`.

## Commands (the single mutation path; same `SessionCommand` model the CLI uses over the unix socket)
`POST /v1/commands` `{"command_id"?,"type","session_id"?,"payload":{}}` -> command JSON (`status` queued|running|succeeded|failed|denied|expired).
`source` is forced to `web` and provenance to `TRUSTED_PAIRED_WEB_COMMAND`. Idempotent by `command_id` (replay returns the stored result, never re-executes).
Commands expire (`COMMAND_TTL_SECONDS`). Long commands return `running` and finish via a `command` frame. Types/payloads: see `remote_models.CommandType`:
`START {goal, permission_policy?, workspace?}` (returns preallocated session_id in payload), `PAUSE RESUME STOP`, `UPDATE_GOAL {goal}`, `ASK {question}` (answered
from session evidence; **never executes**), `ADD_TASK {instruction, permission_level?}` (explicit delegation), `CANCEL_TASK {task_id}`,
`APPROVE_ACTION|DENY_ACTION {approval_id}` (stale/expired approvals rejected), `EXECUTE_RECOMMENDATION {recommendation_id}`, `DISMISS_RECOMMENDATION`,
`FEEDBACK_RECOMMENDATION {recommendation_id, helpful}`, `MUTE_VOICE {minutes?}`, `UNMUTE_VOICE`, `SET_PERMISSION_POLICY {policy}`, `UPDATE_SUBTASKS`, `REQUEST_STATUS`, `REQUEST_SUMMARY`,
plus `ROLLBACK_TASK {task_id}`. `GET /v1/commands/{id}`.

## Realtime
* `GET /v1/ws/sessions/{id}?last_sequence=N` and `GET /v1/ws/user` (WebSocket). Auth by first frame `{"type":"auth","token","last_sequence"?}` (10 s) — never a URL token; Origin checked.
  Frames: `ready`, `event {event: {event_id,sequence,type,timestamp,data}}` (replay of everything > N then live; clients dedupe by event_id, sort by sequence),
  `command {command}`, `status {status}` (daemon/model/voice/observer health), `approval {approval}` (user channel), `session {session}`, `ping`. 4401 = token expired/revoked (re-auth, reconnect with last sequence).
Event types and data shapes: `services/flow/server/events.py` (task.*, recommendation.*, intervention.delivered {voice transcript}, goal.updated, voice.state, efficiency.updated,
observer.health, drift.changed, blocker.changed, metrics.updated, session.*, agent.step, agent.timeline, chat.message).

## Static UI
The daemon serves the packaged web build at `/ui` (same code as Vercel; when served by the daemon the API base is same-origin and pairing is offered for the local machine).
