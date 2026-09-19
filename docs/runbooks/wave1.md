# Wave 1 handoff and limitations

Implemented: a trusted local reference-fixture runner, independent state assertions for two intentionally defective fixtures, content-hashed evidence, SQLite run persistence, actual OpenTelemetry SDK spans, optional OTLP/HTTP exporter, and a development Collector Compose configuration.

Not implemented: HACP or A2A live sessions; persistent trace backend; Collector deployment verification; container isolation for untrusted applications; distributed durable worker leases; application discovery; graph persistence; dashboard; production security. Do not run arbitrary customer code in this runner. SQLite is local-only, not tenant-aware.

Run: `python -m pip install -r requirements-dev.txt`, `python -m unittest discover -s tests -v`, `python scripts/validate_contracts.py`, `python services/runtime/wave1.py agentic`, `python services/runtime/wave1.py fullstack`. Both fixtures should produce FAIL, intentionally. Optional collector commands in `infra/otel/README.md`.

Next: real Collector smoke test and delivery acknowledgment; durable scheduler with worker leases; sandbox boundaries; persistent trace backend; graph persistence; HACP integration only after inspecting actual installed HACP protocol/schema.
