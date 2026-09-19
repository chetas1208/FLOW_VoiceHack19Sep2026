# Current executable scope / release audit

## Implemented and verified locally (run `pytest`)

- New universal UI engine: Chromium-rendered interactions, concurrent redacted
  server file-tail and browser events, independent state-oracle assertions,
  W3C `traceparent` injection into fixture-backend HTTP, OTLP exporter verified
  over actual protobuf HTTP, optional private screenshots, pixel baselines,
  accessibility heuristics, read-only autonomous route audit, cross-run issue
  fingerprints, static-source candidate lookup and offline/served HTML reports.
- New UI benchmark: corrected fixture PASS, injected duplicate-charge defect FAIL
  despite matching UI success copy; generated independent evidence and trace IDs.
  Chromium fixture-only relay is explicitly labeled; native network remains unverified.
- W3C WebDriver client tested against a synthetic standards-shaped server,
  NOT an actual Appium/mobile or desktop session. Unsupported actions explicit.

- Earlier reference fixtures, JSON schemas, SQLite graph, job queue, OTLP/HTTP receiver test.
- Manifest-driven HTTP QA: validated, allowlisted origins (loopback by default),
  explicit steps, bounded response size/time, no redirects, external GET-only
  state oracles, deterministic assertions and four verdicts.
- Content-addressed, hash-checked, redacted default evidence records; run history.
- Known-good and known-defect reference application benchmark with actual HTTP.
- Read-only Playwright discovery and browser interaction against a known fixture
  via optional Python HTTP bridge when Chromium localhost networking is blocked.
  The bridge is **not** a native-network acceptance test.
- FastAPI dashboard, run API, evidence retrieval, graph summary, optional shared
  QA_API_TOKEN, and benchmark endpoint for loopback development only.
- HACP/2.0 schema-checked local bilateral message transport with HMAC, membership,
  deduplication, artifact digest verification, and tests.
- Docker-only fail-closed sandbox adapter; Docker unavailable locally.
- Source discovery for Python and conservative JS/TS/Go/Rust file indexing,
  regex-derived route hints and unapproved draft scenarios; scoped onboarding API.
- Actual protobuf OTLP delivery to a live local receiver and verified persistent
  SQLite span indexing, with sensitive attributes excluded.
- Narrow A2A 0.3 JSON-RPC `message/send`/`tasks/get` benchmark adapter; no conformance claim.
- Fenced worker queue retries/cancellation, scoped environment-token target auth, and CLI.

## NOT completed / must not advertise as completed

- HACP Rust bridge compiled and tested; live Claude/Codex/agent launch and complete A2A conformance.
- Docker container execution verified; strong multi-tenant isolation, production
  secrets and network egress security review.
- Docker Compose Collector deployment actually started and verified; production trace storage/retention and hosted OTLP pipeline.
- Arbitrary framework agent discovery, enterprise auth, user accounts and RBAC.
- Full hosted deployment, cloud load tests, independent external pilots.
- Real mobile/native Appium devices, arbitrary desktop/canvas interfaces,
  and unrestricted Chromium networking in this restricted execution environment.
- Reliable semantic-judge calibration on a meaningful labeled benchmark.
- Statistical claims or universal QA correctness. Four reference examples are not
  a representative sample of third-party projects.

## Commands

```sh
pip install -r requirements-dev.txt
python -m pytest -q
python scripts/validate_contracts.py
python -m benchmarks.benchmark
python -m services.platform.hacp_mailbox
python scripts/demo.py
python -m scripts.ui_demo
python -m services.universal_ui.cli examples/ui-reference.json --discover --max-pages 5
python -m services.universal_ui.cli examples/ui-reference.json --auto-audit --max-pages 5
QA_BROWSER_ACCEPTANCE=1 QA_BROWSER_FIXTURE_RELAY=1 python -m pytest -q tests/test_engine.py -k chromium
PYTHONPATH=. uvicorn services.platform.api:app --host 127.0.0.1 --port 8080
```

Set `QA_API_TOKEN` to a long random secret before serving even trusted loopback
applications on a shared machine; do not bind the development API to 0.0.0.0.
To test an owner-authorized external HTTPS hostname set
`QA_ALLOWED_HTTPS_HOSTS` explicitly, and enforce outbound IP policies outside
this process; hostname allowlisting by itself cannot prevent DNS rebinding.
Do not use synthetic fixture oracles as proof of trust in a third-party oracle.
