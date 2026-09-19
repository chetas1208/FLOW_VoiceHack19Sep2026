# Universal UI engine — developer release

The engine drives **web interfaces with real Playwright browsers**, and has a
**W3C WebDriver/Appium-capable transport** for owner-configured native/mobile
sessions. Native devices and Appium servers are NOT provided or validated in
this environment. Other UI families require a compatible driver; "anything
with a UI" is a product goal, not verified coverage.

## Run a scenario

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
python -m services.universal_ui.cli examples/ui-reference.json --output .local-runs --fail-on-verdict
python -m services.universal_ui.cli examples/ui-reference.json --discover --max-pages 8
python -m services.universal_ui.cli examples/ui-reference.json --auto-audit --max-pages 8
```

Use `QA_CHROMIUM_PATH=/usr/bin/chromium` when appropriate. Replace the example
fixture address with your own app's **authorized, running origin**. A scenario
can set `auth_env` to a `QA_TARGET_TOKEN_*` variable; the Playwright web driver
sends it as an `Authorization: Bearer ...` header only on guarded same-origin
application requests and local fixture relays. Cross-origin redirects and
subresources are blocked before token attachment. The token value is never
written to evidence or event logs. WebDriver/Appium does not yet support this header-injection mode
and fails validation rather than silently running unauthenticated. An HTTP(S)
remote origin must be explicitly listed in `QA_ALLOWED_HTTPS_HOSTS` and must
pass infrastructure egress policy; the host allowlist alone cannot prevent DNS
rebinding. Never expose the local API to the public internet.

### Example workflow

- `goto`, `click`, `fill`, `select`, `wait_for`, `hover`, etc. drive the UI.
- Assertions read DOM text/visibility/title/URL, live console and network
  failures, concurrently tailed local server logs, basic accessibility
  heuristics, visual pixel baselines, and an **independently queried** state API.
- Optional `propagate_trace=true` injects W3C `traceparent` into Playwright
  same-origin requests (also fixture relays), allowing instrumented backends to
  join the QA trace. This is unavailable for uninstrumented native WebDriver.
- A run receives one OTLP trace ID; `qa.ui.run` and `qa.ui.step` spans correlate
  with events and hashed evidence. Configure `QA_OTLP_TRACES_ENDPOINT` and a
  receiver to actually export telemetry; configuration alone is not delivery.
- `FAIL` identifies observed violations, `INCONCLUSIVE` denotes unavailable
  evidence or unsupported driver capabilities, and `INFRA_ERROR` denotes an
  unavailable runtime or external oracle. Missing Playwright browser binaries
  are reported as unsupported capability with remediation text, not as product
  failures. An action-only run is not proof of correctness; write assertions.

For local file tails, set `QA_LOG_ROOT` to an approved directory and reference
an existing regular file in `log_file`. The remote API rejects file tails and
baseline paths. `log_messages` is false by default; even when true, limited
redacted messages are written to the evidence store. Screenshots are off by
default, opt-in screenshots remain private and are **not** served from the
public evidence endpoint. Screenshots can contain sensitive UI content: use
synthetic accounts and review retention policies before enabling. An owner-
approved local `assert_visual` uses an existing baseline under
`QA_BASELINE_ROOT`, exact pixel comparison and an explicit threshold; it is
not perceptual or semantic visual analysis.

### Permissions

Mutating UI actions require `allow_mutations=true`; heuristic destructive
labels require `allow_destructive=true` **and** `QA_ALLOW_DESTRUCTIVE=1`.
These label heuristics are not a comprehensive safety guard. Test against a
staging environment with synthetic data and service-side restrictions.
Read-only discovery does not click, submit forms or auto-approve suggestions;
it skips links that look dangerous but cannot guarantee every GET is safe.
Some applications mutate on GET, so owners must use disposable environments.

The browser blocks third-party origins and downloads. Fixture relay exists
only for local synthetic tests when native Chromium localhost access is
blocked; it executes DOM/JS in Chromium but relays HTTP via Python and must
**never** be reported as real browser networking. The runner labels this mode.

### Driver status

| Interface | Driver | Verification |
| --- | --- | --- |
| Web DOM | Playwright Chromium | Local synthetic E2E browser acceptance, including `auth_env` bearer header fixture coverage |
| Firefox/WebKit | Playwright | Adapter implemented; missing binaries return explicit INCONCLUSIVE unsupported capability |
| Mobile web/native | W3C WebDriver / Appium accessibility ID | Protocol client implemented; device/server unverified |
| Desktop | W3C-compatible server/bridge | Depends on a real desktop driver; unverified |
| Games/canvas/custom pixel surfaces | Additional plug-in needed | Not implemented |

The crawler inventories route/control structure and suggests **unapproved**
scenarios. It does not invent expected results or assert defects without
independent evidence. Root-cause categories are correlations and explicitly
marked `root_cause_confirmed: false`.

## Read-only autonomous mode

`--auto-audit` first inventories same-origin routes, then runs deterministic
console, page-error, HTTP-failure, and basic accessibility checks on each
route. No form submits, button clicks or unapproved tests are generated.
`business_logic_verified` is always `false` for this mode: an accessible
error-free page alone cannot establish correct functionality. Unavailable pages
and incomplete discovery yield INCONCLUSIVE, not an invented PASS.

The API provides `POST /ui/execute`, `/ui/discover`, `/ui/auto-audit`,
`GET /ui/issues`, `/ui/issues/{fingerprint}`, and
`GET /ui/runs/{run_id}/report`. These are single-tenant loopback development
endpoints, **not** a production public SaaS surface.
