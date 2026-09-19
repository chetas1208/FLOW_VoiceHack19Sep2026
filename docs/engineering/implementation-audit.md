# AgentGraph QA Implementation audit

Author: peer a. Counterparty: peer b. Date: 2026-09-19.

This audit records the executable baseline for the extracted AgentGraph QA project. It distinguishes what was verified locally from product goals, partially implemented areas, and infrastructure that still needs a real environment. The baseline source commit is `1d94814 chore: establish imported baseline`.

Peer b joined the HACP session after the initial baseline run. A-001 was proposed by peer a and accepted by peer b before this file was edited. B-001 was proposed by peer b and accepted by peer a for HACP evidence export and bridge documentation.

## Commands Run

These commands were run from `/Users/manubaba/Downloads/agentgraph-qa` unless noted.

| Purpose | Command | Result |
| --- | --- | --- |
| Python version check | `python3 --version` | `Python 3.9.6`; too old for `requirements-dev.txt` |
| Python 3.12 discovery | `command -v python3.12`; `.venv/bin/python --version` | `/opt/homebrew/bin/python3.12`; venv Python `3.12.14` |
| Dependency install | `.venv/bin/python -m pip install -r requirements-dev.txt` | Passed after network access was available |
| Schema validation | `.venv/bin/python scripts/validate_contracts.py` | 11 schemas valid |
| Full test suite | `.venv/bin/python -m pytest -q` | `61 passed, 1 skipped`, `22 subtests passed`, 2 warnings |
| Skip reason detail | `.venv/bin/python -m pytest -q -rs` | skipped `tests/test_engine.py:188`: opt-in real Chromium acceptance |
| Opt-in Chromium bridge | `QA_BROWSER_ACCEPTANCE=1 QA_BROWSER_FIXTURE_RELAY=1 .venv/bin/python -m pytest -q tests/test_engine.py -k chromium` | 1 passed |
| Benchmark | `.venv/bin/python -m benchmarks.benchmark` | 2/2 known defects detected; 0/2 false failures |
| Python HACP mailbox | `.venv/bin/python -m services.platform.hacp_mailbox` | signed local mailbox verified; 3 messages; artifact SHA-256 verified |
| Rust HACP bridge | `cargo run --manifest-path integrations/hacp/Cargo.toml` | compiled and printed settled contract confirmation |
| Vendored HACP tests | `cargo test --manifest-path integrations/hacp/vendor/hacp-1.1.1/Cargo.toml --locked` | all upstream tests passed, including Python file-edge interop |
| Playwright Chromium | `.venv/bin/python -m playwright install chromium` | installed/already satisfied |
| UI demo | `.venv/bin/python -m scripts.ui_demo` | corrected=PASS, defective=FAIL, expected verdicts matched |
| Docker CLI | `docker --version`; `docker ps` | CLI present, daemon unavailable |
| Compose | `docker compose version`; `docker-compose --version` | `docker compose` unavailable; `docker-compose` available |

Peer b independently reported the same Python 3.12 requirement, pytest result after Chromium install, benchmark result, HACP bridge compile/run, and UI demo result in `docs/engineering/baseline-report-peer-b.md`. Peer b also reported a successful ad-hoc native loopback Chromium networking run with fixture relay disabled. I did not independently rerun that ad-hoc script before freezing A-001, so this audit treats native loopback networking as peer-reported and still calls non-loopback external browser networking unverified.

## Implemented And Verified

- Manifest-driven HTTP QA exists in `services/engine/` with schema validation, loopback allowlisting by default, bounded responses, deterministic assertions, and independent GET-only state oracle checks. It is covered by `tests/test_engine.py` and the four-case benchmark.
- The benchmark in `benchmarks/benchmark.py` detects the two known defective fixtures and does not fail the two corrected fixtures in this baseline run.
- Universal UI execution exists in `services/universal_ui/runner.py` and `services/universal_ui/drivers.py`. Chromium fixture execution, DOM assertions, server-log capture, network/console event capture, screenshots, accessibility heuristics, visual pixel checks, independent oracle checks, and HTML reports are exercised by tests and `scripts.ui_demo`.
- The UI demo exercises corrected=PASS and defective=FAIL checkout fixtures. The defective fixture shows UI success while independent backend verification and server logs detect duplicate charge behavior.
- Evidence handling in `services/universal_ui/evidence.py` and `services/engine/store.py` redacts sensitive-looking values and stores content-addressed records. The generated UI evidence redacted fixture tokens and email values while retaining error correlation.
- Persistent issue fingerprints and report generation exist in `services/universal_ui/issues.py` and `services/universal_ui/report.py`.
- OTLP receiver and storage tests pass through the Python test suite; the repo has receiver code in `services/telemetry/receiver.py`.
- The vendored HACP 1.1.1 crate compiles and its own conformance, v2 regression, golden transcript, and Python interop tests pass locally.
- `integrations/hacp/src/main.rs` compiles and runs a single-process HACP/2.0 lifecycle example to settlement.
- The installed `hacp` CLI established a real two-peer session in `.hacp/` with peer `a` and peer `b`, and froze contracts A-001 and B-001.

## Implemented But Unverified

- The W3C WebDriver/Appium-compatible client exists in `services/universal_ui/drivers.py`, but this baseline did not run a real Appium server, mobile device, or desktop driver.
- Firefox and WebKit are selectable through the UI spec/browser driver path, but only Chromium was installed and exercised here.
- Docker sandbox command construction and fail-closed behavior are tested in `tests/test_sandbox.py`, but live Docker execution was not verified because the daemon was unavailable.
- The OTel Collector compose files exist under `infra/otel/`, but compose deployment was not verified. This machine has `docker-compose`, while `docker compose` is unavailable and Docker daemon access failed.
- A2A support in `services/platform/a2a.py` is covered only as a narrow benchmark adapter. No broad A2A conformance claim is supported by the baseline.
- GitHub Actions workflow `.github/workflows/ci.yml` was inspected but not executed on GitHub.

## Partially Implemented

- Read-only UI discovery in `services/universal_ui/discovery.py` inventories same-origin links and a bounded set of controls, but it does not yet build durable workflow graphs for unfamiliar apps, group forms into user intents, infer authenticated flows, or distinguish every discovered fact from business requirements.
- `services/universal_ui/autopilot.py` performs read-only page health checks. It intentionally does not verify business logic and should remain explicit about inconclusive outcomes.
- The knowledge graph and run history exist, but workflow memory, version-to-version UI change detection, and autonomous regression selection are still early.
- Visual regression is exact pixel comparison with a threshold. It is useful for controlled fixtures but not a perceptual visual understanding system.
- Accessibility support is heuristic and deterministic. It is not WCAG certification.
- Failure localization in `services/universal_ui/localize.py` is correlation-oriented and correctly marks root cause as unconfirmed.

## Missing

- Authenticated UI session fixtures are missing. `auth_env` is accepted by the UI spec, but current UI driver/runner code does not apply target auth headers, cookies, or storage state.
- A first-class unsupported-capability result is missing for uninstalled browser engines and unavailable native/mobile/desktop drivers. Current failures may surface as setup errors rather than an explicit unsupported verdict.
- Real Appium/mobile, desktop-native, canvas/game, and custom-rendered UI drivers are not implemented or validated.
- Per-action trace correlation across browser request, backend span, server log line, and state oracle remains limited.
- Production-grade multi-tenant auth, RBAC, evidence isolation, hosted deployment, network egress enforcement, and external pilot validation are not present.
- Statistical accuracy claims are unsupported. The benchmark is a small smoke test, not a representative labeled corpus.

## Incorrect Or Unsafe

- The documented bootstrap order runs pytest before `playwright install chromium`. On a fresh environment this can produce browser executable failures; CI avoids some of this by splitting browser tests into a separate job.
- `integrations/hacp/README.md` and some status text claim Rust/Cargo was absent in the prior environment. That is stale for this host: Cargo 1.98.0 exists and the bridge compiles.
- `services.platform.hacp_mailbox` reports `rust_contract_lifecycle_verified: false` even though the separate Rust bridge was compiled and run in this baseline. The mailbox itself still does not implement the Rust contract engine, so that output needs more precise wording rather than a blanket success flag.
- Raw fixture log files can contain fixture secrets and emails. Stored evidence redacts them, but local logs remain sensitive artifacts.
- A shared `.venv` is awkward for two active agents in one tree. HACP verification commands should prefer peer-specific virtualenvs under `.local-runs/`.

## Unnecessary Or Duplicative

- Hyphenated README-only directories such as `services/agentic-qa/`, `services/fullstack-qa/`, `services/control-plane/`, and `services/evaluation/` overlap with real underscore packages or future areas. They should be consolidated only after review.
- Historical runbooks such as `docs/runbooks/week6*.md`, `docs/runbooks/week14-status.md`, and `docs/runbooks/wave1.md` overlap with `docs/runbooks/current-status.md` and can drift.
- `integrations/hacp/src/main.rs` remains useful as a deterministic single-process bridge example, but it should not be described as the live two-agent runtime. The installed `hacp` CLI is the active two-process collaboration binding for this project.

## CI Gaps

- `.github/workflows/ci.yml` runs `python -m pytest -q --ignore=tests/test_universal_ui.py` in the first job, then runs browser tests after Chromium install. This is reasonable, but the opt-in `tests/test_engine.py -k chromium` test is not run with `QA_BROWSER_ACCEPTANCE=1` in CI.
- CI exercises the UI demo with fixture relay enabled, but does not prove native non-relay browser networking or external application onboarding.
- CI does not validate Docker sandbox execution against a live daemon, OTel Collector compose deployment, Appium, desktop drivers, or external pilots.

## HACP Status

- Session: `s-078c6282209c462b82c5ee6c6e8298a8`.
- Peer `a` owns `docs/engineering/implementation-audit.md`.
- Peer `b` owns `docs/engineering/baseline-report-peer-b.md`, HACP integration files, runtime sandbox, and telemetry receiver files.
- A-001 froze with revision digest `0d2d3ef5ec2bf7c820a9e09aaf17a4fc3668fd8c42351a66a9380a3bf160964c`.
- B-001 froze with revision digest `fb3277404cd75ae32221a90781c8334bdf0532a5df0e01b0c2a64d4ede19a6d7`.

This satisfies the first baseline milestone only. It does not complete the product definition of done: unfamiliar authorized app onboarding, generalized UI execution, concurrent observability, independent verification, durable memory, autonomous regression selection, and product readiness remain open engineering work.
