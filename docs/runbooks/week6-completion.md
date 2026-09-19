# Week 6 completion audit (2026-09-19)

This is a status record, not a declaration of full completion. Do not conflate code written with end-to-end verification.

## Verified in this environment

- All 11 existing JSON schemas validate; 17 automated tests pass.
- Real loopback HTTP server handles two POSTs; independent server-side state oracle detects duplicate charges.
- Real Python agent adapter verifies tool state independently from the agent's reported success.
- OTLP/HTTP exporter POSTs protobuf to a real local test receiver; protobuf is decoded and its trace ID matches the persisted QA run.
- Existing SQLite queue ownership, graph provenance, and synthetic fault injection tests pass.

## Implemented but not verified here

- Real Playwright browser test adapter: Chromium executable is missing. Install Chromium and run `python -m services.fullstack_qa.browser` through an appropriate test harness, or call `verify_browser_retry()` directly.
- Rust HACP bridge: Cargo is absent and github.com DNS is unavailable. The existing bridge has not been compiled, and live agent collaboration is not established.
- OpenTelemetry Collector configuration exists, but Docker is absent; verified OTLP delivery is to a local protocol test receiver, not to the Collector.

## Not yet implemented to the original Week 6 acceptance criteria

- General-purpose repository/framework discovery (current discovery is Python AST only).
- Production-grade isolation of arbitrary user-supplied applications and tool side effects.
- Authenticated, persistent HACP worker transport and live bilateral task settlement.
- Generic external agent framework adapters, full tool interception, fault injection for real services, and broad browser exploration.
- End-to-end correlation across browser, backend, agent, and database for arbitrary applications.

## Run

```
python -m unittest discover -s tests -v
python -m services.runtime.live fullstack --output .local-runs
python -m services.runtime.live agentic --output .local-runs
python -m playwright install chromium
python -c 'from services.fullstack_qa.browser import verify_browser_retry; print(verify_browser_retry())'
```

Never point these reference tests at production. The reference apps contain intentional defects.
