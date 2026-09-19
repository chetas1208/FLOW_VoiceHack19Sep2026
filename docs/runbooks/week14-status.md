# Week 1–14 milestone audit (updated September 19, 2026)

**Release classification: executable local developer MVP, NOT a completed
production platform.** Implementation and local acceptance checks are separate
from rollout, operational security, and real-world customer verification.

| Original phase | Actual status | Evidence or missing gate |
| --- | --- | --- |
| W1 Architecture, contracts, reference apps | Implemented | 11 valid strict core schemas, documented roles and reference fixtures. |
| W2 Telemetry and runtime foundation | Local path implemented | OTLP exporter→receiver→SQLite test passes; official Collector Compose unstarted (Docker missing). |
| W3–4 Discovery and graph | Partial | Python AST, JS/TS static hints, bounded UI route/control crawler, source-route candidate mapping; no universal framework discovery or verified complete coverage. |
| W5–6 Test engines | Partial but substantially expanded | Real HTTP manifests and independent oracle, Chromium-rendered UI actions with simultaneous server/browser logs, WebDriver transport validated against a mock, corrected-vs-defective UI benchmark; external Appium and generic agent adapters remain unverified. |
| W7–8 Verification | Deterministic MVP | Four verdicts, evidence, invariants and four synthetic ground-truth examples; semantic judge calibration absent. |
| W9 Hybrid QA | Local path tested | UI→backend state-oracle checks and W3C `traceparent` propagation verified on local fixtures; no external UI→agent→backend distributed pilot. |
| W10 Memory/regression | Local implemented | SQLite evidence/history, issue fingerprint deduplication and candidate source routes, conservative regression selection; no validated broad change-impact graph. |
| W11 Developer experience | Local implemented | UI/HTTP CLIs, read-only auto-audit, run/issue APIs, offline HTML reports, local dashboard and narrow A2A benchmark skill; no hosted onboarding product. |
| W12 Security/reliability | Development controls only | Redaction, allowlists, lease fencing, sandbox fail-closed adapter; no production tenant isolation or Docker security review. |
| W13–14 External pilot/release | Not completed | No third-party pilot, cloud release, scalability benchmark or deployment readiness approval. |

### Protocol boundaries

HACP 1.1.1 original crate and checksum are vendored. The Rust bilateral
lifecycle example is included and CI has a build job, but cannot compile here
without Cargo. A separately tested Python HACP/2.0 mailbox exchanges messages,
rejects tampering/replay, and verifies artifact bytes. It does not execute Rust
state transitions or launch Claude/Codex.

A2A's benchmark skill uses only `message/send`, `tasks/get` and a card; complete
protocol conformance is not verified. OTLP is the telemetry wire protocol, not
an agent collaboration protocol.

### Current independently rerunnable evidence

See `reports/local-acceptance.json` for the recorded local test status and
`docs/runbooks/current-status.md` for commands and precise blockers. Deliberate
reference defects yield `FAIL`; the test suite passes when those failures are
detected correctly. Do **not** convert a limited benchmark's observed values
into a prediction of detection performance on third-party codebases.

### Universal UI expansion

Run `python -m scripts.ui_demo` for the actual Chromium DOM + Python fixture
relay + independent backend-oracle + concurrent file-tail regression.
Run `python -m pytest -q tests/test_universal_ui.py` for the driver,
accessibility, image diff, OTLP export, WebDriver mock, source candidates,
auto-audit, reporting and privacy tests. Native-browser socket networking,
real Appium and public hosted deployments are not validated.
