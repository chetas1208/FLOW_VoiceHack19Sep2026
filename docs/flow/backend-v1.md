# FLOW backend v1

FLOW is an isolated work-session domain beside ProofHound. It observes semantic
activity supplied by a future local observer; it does not control the user's
computer, capture screens, call a vision model, or deliver voice.

## Architecture and persistence

`services/flow/session_manager.py` owns lifecycle transitions and is shared by
the CLI and FastAPI router. `FlowStore` uses a separate `flow.sqlite3` in
`FLOW_DATA_DIR`, or `QA_DATA_DIR`, or `.local-runs`. SQLite WAL mode and short
connections allow local dashboard reads while an observer writes. Tables are
`flow_sessions`, `flow_observations`, `flow_interventions`, and `flow_events`.
All timestamps are UTC ISO-8601 strings and all IDs are random, sortable-by-time
debug IDs (`ses_`, `obs_`, `int_`, `evt_`). Raw screenshot BLOBs are not stored.

## API and events

With the existing platform server running, FLOW exposes:

* `POST/GET /flow/sessions`
* `GET /flow/sessions/{id}`
* `POST /flow/sessions/{id}/pause`, `/resume`, `/stop`
* `GET/POST /flow/sessions/{id}/observations`
* `GET /flow/sessions/{id}/interventions`
* `GET /flow/sessions/{id}/events?after=N`
* WebSocket `/ws/flow/sessions/{id}`

Events are persisted with monotonically increasing per-session sequences and
published immediately to local WebSocket subscribers. Event types currently
include `session.started`, `session.paused`, `session.resumed`,
`session.completed`, `observation.created`, `metrics.updated`, and
`intervention.proposed`.

## Metrics and drift

Alignment is time-weighted over each sample's interval; unknown intervals are
reported separately and do not become zero alignment. Focus blocks use the
documented `>= 0.70` alignment threshold. Context stability preserves raw
switch counts and conservatively normalizes switches among samples. Progress is
only available when observations explicitly provide `progress_signal`.
The score uses the requested 40/25/15/20 weights when all relevant signals are
available and exposes coverage and confidence beside it. With no evidence,
metrics are unavailable rather than perfect.

Drift uses the recent rolling alignment, requires low alignment for a sustained
duration (30 seconds by default), and emits one proposed CLI intervention for a
session. This is a proposal seam only; there is no ElevenLabs or voice delivery.

## CLI and simulator

```bash
python -m services.flow.cli start --goal "Finish JWT authentication and get all tests passing"
python -m services.flow.cli status --session ses_...
python -m services.flow.cli pause --session ses_...
python -m services.flow.cli resume --session ses_...
python -m services.flow.simulate --session ses_... --interval 1
python -m services.flow.cli stop --session ses_...
```

The simulator marks every observation `source=simulator` and adds
`metadata.simulated=true`. Its timestamps are deterministic relative to the
start of the run; the interval controls both evidence spacing and demo delay.

## Run and test

```bash
export QA_API_TOKEN=local-dev-secret
PYTHONPATH=. uvicorn services.platform.api:app --host 127.0.0.1 --port 8080
python -m pytest tests/flow -q
```

The platform remains localhost-only by default. Placeholder privacy settings
are `FLOW_STORE_SCREENSHOTS=false` and `FLOW_SCREENSHOT_RETENTION_SECONDS=0`.

## Not in v1

Desktop observation, ScreenCaptureKit, adaptive capture, vision/classification,
raw frame retention, final dashboard UI, authentication beyond the existing
local token, cloud sync, OAuth, and voice/ElevenLabs delivery are intentionally
not implemented.
