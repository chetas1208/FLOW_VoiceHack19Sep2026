# Implementation audit and reproducible baseline

Author: peer b (AGENT_B, observability/HACP/infra). Date: 2026-09-19. Host: macOS (Darwin 25.5, arm64). Written before roles were corrected; offered to peer a as input for docs/engineering/implementation-audit.md.
Status: baseline of the unmodified project as extracted from `agentgraph-qa-universal-ui.zip`.



Claims here are limited to what the listed commands showed on this host. Every
fixture is loopback (`127.0.0.1`); nothing below establishes compatibility with
external applications.

## 1. Environment and bootstrap

| Item | Observed | Command |
| --- | --- | --- |
| Default `python3` | 3.9.6, too old: `requirements-dev.txt` requires 3.12+ | `python3 --version` |
| Usable interpreter | `/opt/homebrew/bin/python3.12` (3.12.14) | `which -a python3.12` |
| Rust | cargo 1.98.0 present | `cargo --version` |
| Docker | 29.7.2 CLI present (daemon/sandbox run not yet tested) **(B to confirm)** | `docker --version` |
| HACP runtime | `hacp` (hacp-skill 0.1.0) at `~/.cargo/bin/hacp`, built on `hacp::v2` | `hacp --version` |

**Defect: the documented bootstrap does not work as written on this host.** `python3 -m venv .venv`
produces a 3.9 venv. Use `python3.12 -m venv`.

**Hazard: two peers share one tree.** The shared `.venv` ended up with only `pip` even though
`pip install` exited 0. Another agent process (`codex`) was active in the tree at the same
time, so both peers were most likely writing to the same venv. Peer a now uses a private
`.local-runs/venv-a` (gitignored). Recommendation: one venv per peer (`.local-runs/venv-a`,
`.local-runs/venv-b`), and HACP acceptance commands should call the verifier's own interpreter.

Logs for every command below are in `.local-runs/baseline/` (gitignored and local).

## 2. Baseline results

| Step | Result | Command |
| --- | --- | --- |
| Install | exit 0 | `.local-runs/venv-a/bin/python -m pip install -r requirements-dev.txt` |
| Contract schemas | 11 schemas VALID, exit 0 | `python scripts/validate_contracts.py` |
| Tests, before browser install | **11 failed**, 50 passed, 1 skipped. Every failure: `BrowserType.launch: Executable doesn't exist` | `python -m pytest -q -rs` |
| Browser install | Chromium + headless shell v1243 installed | `python -m playwright install chromium` |
| Tests, after browser install | **61 passed, 1 skipped**, 22 subtests passed (≈30 s) | `python -m pytest -q -rs` |
| Opt-in Chromium bridge test | 1 passed | `QA_BROWSER_ACCEPTANCE=1 python -m pytest -q tests/test_engine.py -k chromium` |
| HTTP/agentic benchmark | 2/2 known defects detected, 0/2 false failures | `python -m benchmarks.benchmark` |
| HACP Python mailbox | `verified: true`, 3 messages, `rust_contract_lifecycle_verified: false` | `python -m services.platform.hacp_mailbox` |
| UI demo | corrected=PASS, defective=FAIL (`state_mismatch`, `concurrent_runtime_error`), `fixture_relay: true` | `python -m scripts.ui_demo` |
| UI demo, **native networking** | corrected=PASS; defective=FAIL (oracle `charges` mismatch + 1 server-log error). The relay is disabled and Chromium fetches from the fixture directly | ad-hoc script: `scripts.ui_demo.manifest(...)` with `fixture_relay=False`, run through `services.universal_ui.runner.execute` |
| Rust HACP bridge | Compiles (hacp 1.1.1 vendored). Runs to `Settled: exact content, size and digest verified; session closed.` exit 0 | `cargo run --manifest-path integrations/hacp/Cargo.toml --target-dir .local-runs/cargo-a` |

**Ordering defect:** the mission bootstrap (§3) and `README.md` run `pytest` before
`playwright install chromium`. On a fresh host that order gives 11 spurious failures. CI
avoids the problem only because `.github/workflows/ci.yml` excludes `tests/test_universal_ui.py`
from the first job and installs Chromium in the second.

**Confidence limit:** the benchmark covers n=4 hand-built HTTP/agentic fixtures and the UI
demo n=2. They show that these specific defects are detected. They say nothing about general
detection rate or false-positive rate.

## 3. Stale or incorrect claims found in docs and code

| Claim | Where | Evidence | Correct statement |
| --- | --- | --- | --- |
| "unrestricted Chromium networking" is unverified / relay needed | `docs/runbooks/current-status.md`, `scripts/ui_demo.py` (hardcoded `native_chromium_networking_verified: False`) | Native run above: PASS/FAIL as expected with no relay | **Verified:** Chromium does real loopback networking on this host. **Still unverified:** non-loopback or external origins |
| "Rust/Cargo is absent … NOT been compiled" | `integrations/hacp/README.md`, `current-status.md` | `cargo run` output above | Bridge compiles and runs the single-process bilateral example. That is still one process playing both roles, not two agents **(B to confirm)** |
| `rust_contract_lifecycle_verified: false` | `services/platform/hacp_mailbox.py` output | Same as above | Stale hardcoded flag **(B owns the file)** |
| UI scenario `auth_env` supports target authentication | `services/universal_ui/spec.py` (schema + env check) | `grep -rn auth_env services/`: the universal UI driver and runner never read it; only the oracle token is used | **Incorrect:** accepted but silently ignored for UI sessions. No UI auth/session fixture exists |
| Firefox/WebKit "adapter implemented" | `spec.py` enum, `docs/runbooks/universal-ui.md` | Only `chromium-1243` in `~/Library/Caches/ms-playwright`. A missing engine fails in `launch`, and `runner.execute` reports `INFRA_ERROR` ("UI setup failed") | Should be an explicit *unsupported / not installed* result (Milestone B) |

## 4. Inventory

### Implemented and verified (on this host, by the commands above)
- Declarative, schema-validated UI scenarios with mutation and destructive-action gates: `services/universal_ui/spec.py` (tests in `tests/test_universal_ui.py`).
- Playwright Chromium execution with same-origin route guard, and concurrent console, page-error and network capture: `drivers.py:PlaywrightDriver`, `runner.py:execute`.
- Native loopback browser networking (see §3), plus the explicitly labelled fixture relay (`drivers.py:_install_fixture_bridge`).
- Independent GET-only HTTP state oracle with JSON-pointer operators: `runner.py:_oracle`.
- Redacted server-log tailing and event stream: `evidence.py:FileTail/EventStream/scrub`.
- W3C `traceparent` propagation and OTLP/HTTP span export to a live receiver: `tests/test_universal_ui.py` (CLI + collector test), `services/telemetry/receiver.py`.
- Pixel-diff visual assertion, opt-in screenshots, heuristic accessibility audit: `evidence.py:image_difference`, `runner.py:_audit_accessibility`.
- Read-only same-origin route/control discovery and read-only health autopilot: `discovery.py`, `autopilot.py`.
- Cross-run issue fingerprints, static-source candidate lookup, offline HTML report: `issues.py`, `localize.py`, `report.py`.
- Content-addressed evidence store and SQLite run history: `services/engine/store.py`.
- Manifest-driven HTTP QA and reference benchmark: `services/engine/`, `benchmarks/benchmark.py`.
- HACP Python mailbox (HMAC, membership, dedup, digest check): `services/platform/hacp_mailbox.py`.
- Rust HACP example bridge compiles and settles a contract in one process: `integrations/hacp/src/main.rs`.
- A real two-process HACP runtime exists outside the repo: the `hacp` CLI (hacp-skill 0.1.0) uses `hacp::v2` contracts with durable `.hacp/` state. This session (`.hacp/session.json`) was started by peer a with it.

### Implemented but unverified
- `WebDriver` client (`drivers.py:WebDriver`): tested only against a synthetic W3C-shaped server. No Appium/device or desktop driver has been run.
- Firefox/WebKit engines: selectable in the spec, but the binaries are not installed.
- Docker sandbox adapter (`services/runtime/sandbox.py`) and OTel Collector compose (`infra/otel/compose.yaml`): not yet run here **(B to confirm)**.
- A2A adapter (`services/platform/a2a.py`): narrow benchmark only, no conformance claim.
- GitHub Actions `hacp-rust-bridge` job: has never run on GitHub (comment in `ci.yml`).

### Partially implemented
- **Onboarding an unfamiliar app** (my Milestone A gap):
  - `discovery.py` reads only `h1/h2`, `a[href]` and ≤60 controls.
  - It has no accessibility-tree snapshot and no form/field grouping.
  - It does not wait for SPAs to settle (`domcontentloaded` only) and cannot find routes reached without `<a href>`.
  - Its drafts are bare locators with no steps. They are not runnable scenarios and do not separate *discovered* facts from *inferred* intent.
- Workflow graph: `graph.py` stores `NAVIGATES_TO` page edges only. There is no action→state transition model.
- Visual regression: exact pixel ratio only, with no perceptual or region masking.
- Accessibility: three heuristics, which is not WCAG conformance.

### Missing
- UI authentication/session fixtures (storage state, cookie/header injection from an env secret kept outside model context).
- Per-step network/request correlation IDs linking browser requests to backend spans beyond a single run-level trace.
- Explicit `UNSUPPORTED` verdict or driver-availability probe for engines and platforms.
- Canvas/game and desktop-native drivers.
- Version-to-version change detection for UI inventory (Milestone G).
- Multi-tenant auth/RBAC, production deployment **(B)**.

### Incorrect or unsafe
- `auth_env` is accepted for UI scenarios but ignored (see §3). Users may believe tests ran authenticated when they did not.
- Stale "unverified/absent" flags in docs, the demo and the mailbox output (see §3). These understate reality, and hardcoded flags can drift in either direction.
- Shared-venv races when two agents bootstrap in one tree (see §1).

### Unnecessary or duplicative
- `services/agentic-qa/`, `services/fullstack-qa/`, `services/control-plane/`, `services/evaluation/` are README-only directories beside the real `agentic_qa/` and `fullstack_qa/` packages. They are candidates for consolidation, not deletion without review.
- `docs/runbooks/week6*.md`, `week14-status.md`, `wave1.md` are historical status notes that overlap `current-status.md`.
- `integrations/hacp/src/main.rs` (single-process example) partly duplicates what the external `hacp` CLI now does for real two-process sessions **(B to decide)**.

## 5. CI acceptance gaps (`.github/workflows/ci.yml`)
- `tests/test_engine.py:188` (`test_chromium_fixture_bridge`) is skipped unless `QA_BROWSER_ACCEPTANCE=1`, and the CI step that sets it runs `scripts.ui_demo`, not pytest. The opt-in test never runs in CI.
- The UI demo in CI uses only the fixture relay. Native networking is never exercised in CI.
- The Docker sandbox, Collector compose and Appium paths have no CI job.
- The `hacp-rust-bridge` job has never run on GitHub. Locally it compiles (see §2).

## 6. Collaboration process deviations (recorded honestly)
- Mission §13 asks for separate git worktrees. The `hacp` runtime keeps its session in `.hacp/` of **one shared project directory**, and acceptance commands run from that root. File-level ownership enforced by `hacp` contracts replaces worktree isolation. Git is used for baseline and integration commits.
- In the `hacp` CLI the proposer of a contract is its owner and implementer. "A proposes a task that B implements" is therefore carried out as: A requests the task over HACP (`ask`), B proposes terms, A reviews and accepts, B implements and submits, A verifies.
