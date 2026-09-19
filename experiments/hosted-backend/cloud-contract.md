# FLOW cloud wire contract (v1)

Single source of truth for the cloud API, used by the device daemon/CLI (`services/flow`), the cloud
(`services/flowcloud`) and the web app (`web/`). Shared domain models live in
`services/flow/remote_models.py`; their `to_dict()` output **is** the JSON shape for those entities.

## Conventions

* Base URL: `FLOW_API_URL` (profile default in `services/flow/profiles.py`). All paths are under `/v1`.
* JSON only. `Content-Type: application/json`. Times are ISO-8601 UTC. Ids match `^[A-Za-z0-9_-]{8,80}$`.
* Auth: `Authorization: Bearer <token>`.
  * **device token** — FLOW-issued access JWT (15 min, `typ=access`, claims `sub`=user, `did`=device).
  * **web token** — IdP JWT verified against OIDC JWKS (remote mode) or a dev token from `POST /v1/dev/login`
    (only when `FLOW_ENV` is not production and `FLOW_AUTH_MODE=local`).
  * Both principals may read the user's data. Only device tokens may ingest or ack. Web tokens issue commands.
* Errors: HTTP status + `{"error": "<code>", "message": "...", "request_id": "..."}`.
  Codes: `unauthorized`(401) `forbidden`(403) `not_found`(404) `conflict`(409) `validation_error`(422)
  `payload_too_large`(413) `unsupported_media_type`(415) `rate_limited`(429, `Retry-After`) `device_offline`(409)
  `command_expired`(409). Cross-tenant access is always `not_found`.
* Pagination: `?limit=` (1..100) and opaque `?cursor=`; responses `{"items": [...], "next_cursor": "..."|null}`.
* Idempotency: every ingest item has a client id; a repeat returns 200 `{"status":"duplicate"}` (201 `created` first time).
* Sequences: observations and events carry per-session monotonic `sequence` (1,2,3...) assigned by the device.
  Responses include `sync: {"highest_sequence", "received", "missing": [...]}` so the device can resend gaps.

## Device authorization (CLI login)

1. `POST /v1/cli/auth/requests` (public, rate limited)
   `{"device": {"device_id","name","os","architecture","flow_version"}, "code_challenge","code_challenge_method":"S256","state","nonce"}`
   -> `201 {"auth_request_id","user_code","authorization_url","expires_at","interval"}`.
   `authorization_url` = `{web_url}/cli/auth?request=<auth_request_id>`; no secret is in the URL.
2. Web (signed in, web token): `GET /v1/cli/auth/requests/{id}` ->
   `{"id","status","device":{name,os,architecture,flow_version},"user_code","expires_at"}`;
   `POST /v1/cli/auth/requests/{id}/approve` -> `{"status":"approved"}`; `.../deny`.
3. CLI polls `POST /v1/cli/auth/token` `{"auth_request_id","device_id","code_verifier"}` every `interval` s.
   Pending -> `400 {"error":"authorization_pending"}`; too fast -> `400 slow_down`; denied -> `400 access_denied`;
   expired -> `400 expired_token`; replay/invalid PKCE -> `400 invalid_grant`.
   Success -> `200 {"access_token","token_type":"Bearer","expires_in","refresh_token","refresh_expires_in",
   "user":{"id","email"},"device":{"id","name"},"state","nonce"}`. The CLI must check `state` and `nonce`.
4. `POST /v1/auth/refresh` `{"refresh_token","device_id"}` -> same token fields (refresh token **rotates**; reuse of a
   spent token revokes the family). `401 invalid_grant` means the device must `flow login` again.
5. `POST /v1/auth/logout` `{"refresh_token"}` -> 204.
6. `GET /v1/me` -> `{"id","email","principal":"device"|"web","device_id"?}`.
7. `GET /v1/devices` -> `{"items":[{"id","name","os","architecture","flow_version","created_at","last_seen_at","revoked_at",
   "presence":{"state":"online"|"degraded"|"offline","last_heartbeat_at","health":{...},"active_sessions":[...]}}]}`.
   `DELETE /v1/devices/{id}` (web token, or the device itself) -> 204; revoked device: refresh fails, ingest 401.
8. `POST /v1/dev/login` `{"email"}` -> `{"access_token"}` (development only).

## Session ingest (device token; the device may only write its own sessions)

* `POST /v1/sessions` `{"id","goal","started_at","metadata"}` -> 201/200. `id` is the local session id (same id everywhere).
* `POST /v1/sessions/{id}/observations` (ObservationIn) and `.../observations:batch` `{"observations":[<=100]}` ->
  `{"results":[{"id","sequence","status":"created|duplicate|conflict"}],"sync":{...}}`.
  ObservationIn: `id, sequence, timestamp, activity, category, goal_alignment, progress_signal, confidence, task_phase,
  application, activity_type, source, blocker` (unknown fields rejected — no pixels, no window titles).
* `POST /v1/sessions/{id}/events` (EventIn `{"id","sequence","type","timestamp","data"}`) and `.../events:batch`.
  Allowed `type` values are enumerated in `services/flowcloud/schemas.py::EVENT_TYPES`.
  `session.paused|resumed|completed` events also move the session status (highest sequence wins).
* `POST /v1/sessions/{id}/interventions`, `POST /v1/sessions/{id}/segments` (upsert by `id`, higher `revision` wins).
* `POST /v1/sessions/{id}/entities:batch` `{"items":[{"kind","id","revision","data"}]}` (<=100), kinds:
  `task` (DelegatedTask), `approval` (ActionApproval), `recommendation` (ActionRecommendation),
  `subtask` (Subtask), `goal_version` (GoalVersion; `id` = str(version)), `chat` (`{id,question,answer,asked_at,answered_at,source}`),
  `runtime_state` (`{status: RuntimeStatus, observer, vision, voice, agent, voice_muted_until, permission_policy, goal_version, goal_state}`;
  single row, `id` = "current"). Higher `revision` replaces; equal is a duplicate; lower is stale. `status` column = `data.status`.
* `PUT /v1/sessions/{id}/summary` (SummaryIn) -> new immutable version; identical content is a duplicate.
* `POST /v1/sessions/{id}/stop` `{"ended_at"?, "summary"?}` -> completes the session (idempotent). Late ingests are still accepted.
* Session ingest may target completed sessions (offline sync catch-up).

## Reads (device or web token; tenant scoped)

* `GET /v1/sessions?status=&device_id=&since=&until=&limit=&cursor=` -> `{"items":[SessionOut],"next_cursor"}`.
  SessionOut: `{"id","goal","status","device_id","device_name","started_at","ended_at","updated_at","runtime_state"|null,"goal_version"}`.
  `status` in DB is one of the RuntimeStatus values.
* `GET /v1/sessions/{id}` -> `{"session","summary"|null,"metrics","segments","interventions","goal_history","subtasks"}`.
* `GET /v1/sessions/{id}/observations?after_sequence=&limit=` and `.../events?after=&limit=` (paged by sequence).
* `GET /v1/sessions/{id}/entities?kind=&status=&limit=` -> `{"items":[{"kind","id","revision","status","data","updated_at"}]}`.
* `GET /v1/approvals?status=pending` -> user-wide approval entities (for the "ACTION NEEDED" badge).
* `GET /v1/sessions/{id}/report` -> structured report (goal, durations, alignment, focus, context stability, progress, score,
  coverage, confidence, segments, blockers, drift periods, interventions, recommendations, **human vs agent activity**,
  tasks, approvals, voice interventions).
* `GET /v1/sessions/{id}/live` ->
  `{"session":{...},"presence":{state,last_heartbeat_at,health},"current":{"activity","task_phase","alignment","drift","blocker","category"},
    "metrics":{...latest metrics.updated data...},"efficiency":{...latest efficiency.updated data...},"latest_segment":{...},
    "observer_health":{...},"voice":{"state","muted_until"},"agent":{"status","current_task","pending_approvals":n},
    "goal":{"text","version","state","subtasks":[...]},"recommendation":{...}|null,"tasks":[...last 20...],
    "approvals":[...pending...],"last_event_sequence":n,"sync":{"observations":{...},"events":{...}}}`.

## Commands (remote control)

`SessionCommand` (see remote_models). Web/CLI create; the device executes; everybody observes.

* `POST /v1/commands` (web or device token) `{"command_id"?,"type","session_id"?,"device_id"?,"payload":{},"source":"web"|"cli"}`
  * `START` needs `device_id` (must be online) and returns a preallocated `session_id`; other types need `session_id`
    (device resolved from the session). Repeating a `command_id` returns the existing command (idempotent).
  * Only `STOP, PAUSE, MUTE_VOICE, UNMUTE_VOICE` may be queued for an **offline** device; others -> 409 `device_offline`.
  * `expires_at` defaults from `COMMAND_TTL_SECONDS`; expired queued commands become `expired` and are never delivered.
  * Payloads: `START {goal, permission_policy?}`, `UPDATE_GOAL {goal}`, `MUTE_VOICE {minutes?}`, `ADD_TASK {instruction,
    permission_level?}`, `CANCEL_TASK {task_id}`, `APPROVE_ACTION|DENY_ACTION {approval_id}`,
    `EXECUTE_RECOMMENDATION {recommendation_id}`, `ASK {question}`, `DISMISS_RECOMMENDATION {recommendation_id}`,
    `FEEDBACK_RECOMMENDATION {recommendation_id, helpful: bool}`, `SET_PERMISSION_POLICY {policy}`,
    `UPDATE_SUBTASKS {subtasks:[{id?,title,status}]}`, `REQUEST_STATUS|REQUEST_SUMMARY|PAUSE|RESUME|STOP {}`.
* `GET /v1/commands/{command_id}` and `GET /v1/sessions/{id}/commands?limit=` -> command JSON with `status`, `result`.
* `POST /v1/commands/{command_id}/ack` (device token; HTTP fallback for the WS ack) `{"status","result"?}`.
* Status flow: `queued -> delivered (sent to device socket) -> running -> succeeded|failed|denied`; also `expired`, `cancelled`.
  Socket delivery is **not** success. Delivery is at-least-once; the device dedupes by `command_id` (exactly-once effect).

## Device realtime channel — `GET /v1/ws/device` (WebSocket, outbound from the Mac)

Auth: `Authorization: Bearer <device access token>` header, or first frame `{"type":"auth","token":"..."}` within 10 s.
Never a query-string token. The device reconnects with exponential backoff (1 s .. 30 s) and re-authenticates with a fresh token.

Device -> cloud frames:
`{"type":"hello","device_id","flow_version","active_sessions":[ids],"health":{...}}`,
`{"type":"heartbeat","health":{"observer","vision","voice","agent","daemon"},"active_sessions":[ids]}` every 20 s,
`{"type":"ack","command_id","status":"running|succeeded|failed|denied","result":{...}}`,
`{"type":"events","session_id","events":[EventIn...]}` (optional low-latency path; same validation and idempotency as HTTP).

Cloud -> device frames:
`{"type":"ready","server_time"}`, `{"type":"command","command":{...SessionCommand...}}` (all still-valid queued/delivered
commands are re-sent after `hello`, oldest first), `{"type":"ping"}`, `{"type":"revoked"}` (then close 4401).

Presence: `online` = live socket + heartbeat within 60 s; `degraded` = online with any health component `error`;
`offline` otherwise. A missed heartbeat never stops the local session.

## Viewer realtime channels (web/CLI attach)

* `GET /v1/ws/sessions/{id}?last_sequence=N` — auth by `Authorization` header or first frame
  `{"type":"auth","token":"...","last_sequence":N}`. Origin is checked against `FLOW_ALLOWED_ORIGINS`.
  Frames: `{"type":"ready","session_id","last_sequence"}`, `{"type":"event","event":{event_id,sequence,type,timestamp,data}}`
  (replay of everything > N, then live; out-of-order events are delivered, clients sort by `sequence` and dedupe by `event_id`),
  `{"type":"command","command":{...}}` (status changes), `{"type":"presence","presence":{...}}`, `{"type":"ping"}`.
  Closed with 4401 when the token expires (client refreshes and reconnects with its last sequence).
* `GET /v1/ws/user` — same auth; frames `{"type":"presence","device_id","presence":{...}}`, `{"type":"approval","approval":{...}}`,
  `{"type":"session","session":{...SessionOut}}`.

## Event data shapes (added by the remote layer)

* `task.*`: `{"task": DelegatedTask}`; `task.tool_started|completed`: `{"task_id","tool","args_summary","exit_code"?,"summary"?}`.
* `task.approval_requested|approval_resolved`: `{"approval": ActionApproval}`.
* `recommendation.created|updated`: `{"recommendation": ActionRecommendation}`.
* `intervention.delivered`: `{"intervention_id","message","channel":"voice","level","recommendation_id"?}` (voice transcript).
* `goal.updated`: `{"version","goal","source","effective_at"}`. `voice.state`: `{"state":"ready|muted|unavailable","muted_until"?}`.
* `chat.message`: `{"id","question","answer","source"}`. `command.acked`: `{"command_id","status"}`.
