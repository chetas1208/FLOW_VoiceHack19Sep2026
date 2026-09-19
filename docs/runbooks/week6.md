# Weeks 3–6 implementation status and execution

## Delivered vertical slices
- AST-based Python source discovery and provenance-backed SQLite graph; unsupported languages and dynamic edges explicitly unknown.
- Local fixture scenario runner for agentic, fullstack and synthetic timeout-after-commit cases; independent state assertions and hashed evidence.
- Durable SQLite queue with atomic claims, worker leases, heartbeats and completion ownership checks; no automatic distributed worker or sandbox.
- Existing Wave 1 OpenTelemetry SDK and optional OTLP/HTTP export configuration retained.
- Rust HACP v2 bilateral agreement bridge pinned to the upstream documented revision. Not compiled or connected to agents in this environment.

## Try locally
`python3 -m unittest discover -s tests -v`
`python3 scripts/validate_contracts.py`
`python3 services/runtime/worker.py --submit agentic`
`python3 services/runtime/worker.py`
`python3 services/runtime/worker.py --submit fault-injection`
`python3 services/runtime/worker.py`
`cargo run --manifest-path integrations/hacp/Cargo.toml` (requires Rust + network)

## NOT DONE: blockers before genuine Week 6 acceptance
- Live HACP agent sessions and authenticated transport; upstream Rust bridge must compile and be integrated with real CLI adapters.
- Live Collector export receipt, persistent end-to-end OTLP correlation, and a trace backend.
- Actual browser exploration, browser-level Playwright execution, API integration and database inspection against user apps.
- Production-grade sandbox, credential isolation, cleanup, tenant security, crash recovery orchestration.
- Real tool interception and fault injection in arbitrary agent frameworks; only synthetic fixture faults implemented.
- General scenario generation, model judges, and benchmark coverage beyond reference fixtures.

The delivered code is a tested foundation and partial Weeks 3–6 vertical slice, not a complete six-week platform. Never run untrusted applications in the local worker.
