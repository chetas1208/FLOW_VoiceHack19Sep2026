# ProofHound

Autonomous QA foundation for web UIs, full-stack, tool-using agentic, and hybrid applications.
**Current release: executable local universal-UI developer engine; NOT universal coverage or production-ready hosted SaaS.**

The previous Week 1–14 project scaffold has been extended with a real manifest-based
HTTP QA engine, independently queried state oracles, restricted browser discovery,
OTLP instrumentation, a provenance graph, durable fixture jobs, a local dashboard,
limited HACP wire and A2A adapters, and a four-case known-good/known-bad benchmark.
See [`docs/runbooks/current-status.md`](docs/runbooks/current-status.md) for
verified functionality and unverified release gates. The new reusable UI engine
is documented in [`docs/runbooks/universal-ui.md`](docs/runbooks/universal-ui.md).

## Quick start

```bash
python -m pip install -r requirements-dev.txt
python scripts/validate_contracts.py
python -m pytest -q
python scripts/demo.py
python -m scripts.ui_demo  # launches corrected and defective real-HTTP UI fixtures
```

Expected demo behavior: the *defective* agentic and full-stack fixtures return
`FAIL`, and their *corrected* counterparts return `PASS`. `demo-report.json`
contains the run IDs, trace IDs, benchmark result and signed two-peer HACP
mailbox exchange. The HACP mailbox verifies local wire delivery; it is NOT the
same as a compiled HACP Rust lifecycle or an external coding-agent launch.

## UI-to-backend QA and concurrent logs

The `services/universal_ui/` engine adds a declarative Playwright UI driver,
a W3C WebDriver/Appium-compatible transport, live redacted browser/network
and owner-approved server-log collection, independent HTTP state oracles,
optional W3C trace propagation, OTLP run/step spans, private failure screenshots,
visual pixel baselines, limited accessibility heuristics, content-addressed
evidence, issue deduplication, heuristic source-route localization and offline
HTML bug reports. Missing capabilities produce `INCONCLUSIVE`, not imaginary PASS.

```bash
# Fully self-contained end-to-end demonstration; two HTML reports in .local-runs/ui-demo
python -m scripts.ui_demo
# Against YOUR authorized, running application (edit origin and assertions first)
python -m services.universal_ui.cli examples/ui-reference.json --output .local-runs --fail-on-verdict
# Inventory links and controls without clicking, then auto-audit read-only page health
python -m services.universal_ui.cli examples/ui-reference.json --discover --max-pages 8
python -m services.universal_ui.cli examples/ui-reference.json --auto-audit --max-pages 8
```

The example JSON has **basic UI-health assertions only**; it does not assert
order idempotency. Provide an independent `oracle_origin` and `assert_oracle`
step for business correctness. The demo includes those checks. For local logs,
set `QA_LOG_ROOT` and use an existing `log_file` only with the local CLI; the
remote development API rejects local file paths. Screenshot and trace-header
propagation are opt-in. For details and native-app limitations, read the UI
runbook linked above.

## Dashboard and API

```bash
export QA_API_TOKEN='replace-with-long-random-local-secret'
PYTHONPATH=. uvicorn services.platform.api:app --host 127.0.0.1 --port 8080
```

Browse `http://127.0.0.1:8080/dashboard` and enter username `qa` and your
`QA_API_TOKEN` as the Basic Auth password. API clients can instead supply
`x-qa-api-token`. Browse `/docs` for documented local API endpoints.

Main endpoints:

- `POST /engine/execute` — execute a validated, authorized HTTP manifest;
- `GET /engine/runs` and `/engine/runs/{id}` — persisted results;
- `GET /engine/evidence/{sha256}` — hash-verified, redacted evidence;
- `POST /benchmark/run` and `GET /benchmark/latest` — calibration fixtures;
- `POST /projects/discover` — bounded multi-language source discovery and unapproved scenario suggestions;
- `GET /graph/summary` — provenance graph counts;
- `GET /telemetry/traces/{trace_id}` — persisted, allowlisted OTLP spans;
- `GET /dashboard` — browser-readable history;
- `POST /ui/execute`, `/ui/discover`, `/ui/auto-audit` — UI execution and read-only exploration;
- `GET /ui/issues` and `/ui/issues/{fingerprint}` — cross-run finding index;
- `GET /ui/runs/{run_id}/report` — redacted offline-style HTML report;
- `GET /.well-known/agent-card.json` and `POST /a2a` — limited A2A benchmark skill;
- legacy `/jobs` and `/workers/run-once` — trusted reference-fixture jobs.

**Do not expose this single-tenant development API to the internet.** The
endpoint allowlist is not a network egress firewall, and a shared development
token is not enterprise RBAC.

## Test an owner-authorized application

Define a JSON manifest specifying an HTTP origin, method/path/JSON steps, and
expected assertions. State verification can query a separate `oracle_base_url`
using GET requests. No shell commands, source imports, or arbitrary Python can
be submitted in a manifest. Targets are restricted to loopback by default.

```bash
python -m services.engine.cli my-scenario.json --output .local-runs --fail-on-verdict
```

The CLI returns exit code 1 for a failing/inconclusive application and 2 for
infrastructure errors. See [`docs/runbooks/manifest.md`](docs/runbooks/manifest.md)
for a copy-paste manifest, credential handling, and security restrictions.

## OTLP

```bash
mkdir -p .local-runs
export QA_DOCKER_UID="$(id -u)" QA_DOCKER_GID="$(id -g)"
docker compose -f infra/otel/compose.yaml up --build -d
export QA_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces
python -m services.engine.cli my-scenario.json
```

An end-to-end integration test starts a real local OTLP/HTTP receiver, sends
actual protobuf traces from the QA runner, and confirms spans were written
to SQLite. The development Compose configuration additionally connects a
Collector to that persistent receiver; **the Docker/Collector deployment has
not been verified here** because Docker is unavailable. The receiver supports
traces only; production needs a supported backend and retention controls.

## HACP and A2A

The original, checksum-verified HACP 1.1.1 crate is included at
`integrations/hacp/vendor/` and extracted to the Rust adapter's local path.
Run `cargo run --manifest-path integrations/hacp/Cargo.toml` where Cargo exists.
The Python HACP/2.0 transport demo uses official schema shapes and canonical
JSON, bilateral membership, HMAC signatures, replay prevention and artifact
hash verification, but does NOT implement the full HACP contract state engine.

The A2A adapter advertises protocol version 0.3.0 and implements only an
explicitly limited benchmark skill via `message/send` / `tasks/get`. It has NOT
passed the protocol's complete conformance suite and does not launch LLM agents.

## Current limitations

No verified live Docker sandbox, compiled HACP adapter, full remote A2A
interoperability, Appium device pilot, unrestricted native Chromium networking,
real external customer pilot, production multi-tenancy or semantic-judge calibration. A four-case fixture benchmark is only a smoke test.
Do not claim all 14 original milestones are production-complete; see the audit.
