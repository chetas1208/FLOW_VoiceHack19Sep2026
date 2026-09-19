# Capability matrix

As of 2026-09-19, macOS arm64, Playwright 1.63 (Chromium 1243), Docker 29.7 on Colima.
"Verified here" means an executable test or demo on this host produced the result. It does not mean general compatibility.

## UI families

| UI family | Driver in code | Verified here | Unsupported or unverified | Needed to close the gap |
| --- | --- | --- | --- | --- |
| Web, Chromium | `PlaywrightDriver` (`services/universal_ui/drivers.py`) | Real rendering with native loopback networking. Token-gated onboarding, form discovery and ARIA snapshot (`tests/test_onboarding_ui.py`). Same-origin-only auth headers with no cross-origin leak through redirects or subresources (A-003 regression tests). Concurrent log tail, OTLP, oracle (`scripts/onboarding_demo.py`). | Non-loopback or external origins (the code supports them through `QA_ALLOWED_HTTPS_HOSTS`, but they were not exercised). Cookie or login-form sessions: only bearer `auth_env` exists. SPA routes reachable without `<a href>`. After a server-side same-origin redirect, `page.url` keeps the original path. | An owner-authorized external staging pilot, storage-state and login fixtures, and a click-driven SPA explorer |
| Web, Firefox / WebKit | `PlaywrightDriver` with `browser: firefox\|webkit` | Missing engine returns an explicit INCONCLUSIVE "browser engine not installed" result (A-002 tests) | Engines not installed, so no run | `python -m playwright install firefox webkit`, then run the UI suite with `browser` set |
| Mobile web / native (iOS, Android) | `WebDriver` (W3C + Appium `accessibility id`) | Only against a synthetic W3C-shaped HTTP server (`tests/test_universal_ui.py`) | No Appium server, emulator or device. `discover()`, hover/select/check/press, visual and accessibility checks raise UnsupportedAction (INCONCLUSIVE) | A running Appium server and a device or emulator |
| Desktop native (Windows, macOS, Linux) | `WebDriver` if a W3C bridge exists (WinAppDriver, Appium Mac2) | No | No desktop driver was run | A bridge plus a target app |
| Canvas, games, custom-pixel UIs | None | No | No semantic locators; only pixel screenshot diff exists for web | A vision or coordinate driver plug-in |
| HTTP APIs (no UI) | `services/engine` manifest runner | Benchmark: 2/2 known defects found, 0/2 false failures | n=4 fixtures | A labelled corpus for accuracy claims |
| Agentic apps | `services/agentic_qa`, A2A adapter | Benchmark fixture only | No A2A conformance | Real agent targets |

## Cross-cutting capabilities

| Capability | Status | Evidence |
| --- | --- | --- |
| Independent state verification | HTTP GET JSON oracle. Mutating drafts cannot run until an owner approval adds one. | `onboard.approve`, `tests/test_onboarding_ui.py` |
| Concurrent observability | Server-log tail, browser console and network events, OTLP runner spans plus instrumented backend spans, per-step correlation (trace-linked vs time-window) | `services/telemetry/correlate.py`, `tests/test_correlate.py`, demo |
| OTel Collector deployment | Compose stack verified live after fixing a gzip rejection | `tests/test_otel_compose_live.py` (opt-in) |
| Sandbox isolation | Docker: no network, read-only mounts, non-root, container removed on timeout, infrastructure errors are not reported as test results | `tests/test_sandbox_live.py` (opt-in) |
| Change detection and regression selection | Structure digest per page; selects changed pages plus previous failures. Backend-only changes are invisible to it. | `onboard.diff`, `onboard.select_regressions` |
| Bug reports | Markdown with verified / observed / hypothesis sections and a reproducible scenario; HTML report | `services/universal_ui/bugreport.py` |
| Multi-tenant auth, RBAC, egress control | Not implemented (single-tenant dev API) | — |

## Confidence limits

The end-to-end demo uses one synthetic app written for it (`reference_apps/lending_library.py`), on loopback, with owner expectations supplied by the script. It shows that the pipeline works end to end. It gives no detection rate or false-positive rate for real applications.

Work after the HACP session closed (onboarding, bug report, this matrix) was verified only by peer b's own tests. The second agent was unavailable to review it.
