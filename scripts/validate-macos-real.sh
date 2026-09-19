#!/usr/bin/env bash
# Guided real-Mac validation runbook for FLOW. Produces artifacts/macos-validation.json.
#
#   scripts/validate-macos-real.sh                       # install from this checkout (pip install .)
#   FLOW_RELEASE=./dist scripts/validate-macos-real.sh   # install from a release dir (wheels)
#   FLOW_RELEASE=https://host/flow_agent-0.2.0-py3-none-any.whl scripts/validate-macos-real.sh
#
# Environment:
#   FLOW_VENV                      venv location (default ./.flow-validate-venv)
#   FLOW_ARTIFACT                  output JSON (default artifacts/macos-validation.json)
#   FLOW_VALIDATE_ARGS             extra args for `flow validate macos`, e.g. "--scenario env,observer"
#   FLOW_VALIDATE_NON_INTERACTIVE  1 = skip the guided scenarios (they report "skipped")
#   FLOW_VALIDATE_ALLOW_PARTIAL    1 = exit 0 unless something FAILED (default: anything but verified fails)
#   FLOW_VALIDATE_ALLOW_NON_MACOS  1 = run on a non-Mac (everything macOS-only reports not_configured)
#   FLOW_MACOS_HELPER              prebuilt flow-macos-observer (otherwise built with swift if available)
#
# STATUS: IMPLEMENTED_ENVIRONMENT_UNVERIFIED (author had no Mac; only `bash -n` and Linux dry runs).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${FLOW_VENV:-$PWD/.flow-validate-venv}"
ARTIFACT="${FLOW_ARTIFACT:-artifacts/macos-validation.json}"
PYTHON="${PYTHON:-python3}"
INTERACTIVE=1
[ "${FLOW_VALIDATE_NON_INTERACTIVE:-0}" = "1" ] && INTERACTIVE=0
[ -t 0 ] || INTERACTIVE=0

say() { printf '\n== %s\n' "$*"; }
pause() { [ "$INTERACTIVE" = "1" ] && { printf '%s ' "$1"; read -r _; } || true; }

if [ "$(uname -s)" != "Darwin" ]; then
  if [ "${FLOW_VALIDATE_ALLOW_NON_MACOS:-0}" != "1" ]; then
    echo "This runbook validates FLOW on macOS; found $(uname -s)." >&2
    echo "Set FLOW_VALIDATE_ALLOW_NON_MACOS=1 to run anyway (macOS checks will be not_configured)." >&2
    exit 2
  fi
  echo "WARNING: not macOS; macOS-only checks will honestly report not_configured." >&2
fi

say "1/6 Python virtualenv ($VENV)"
command -v "$PYTHON" >/dev/null 2>&1 || { echo "python3 not found" >&2; exit 2; }
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || { echo "FLOW needs Python 3.11+" >&2; exit 2; }
[ -d "$VENV" ] || "$PYTHON" -m venv "$VENV"
# shellcheck disable=SC1091
. "$VENV/bin/activate"
python -m pip install --quiet --upgrade pip

say "2/6 Install FLOW with vision + voice extras"
RELEASE="${FLOW_RELEASE:-}"
if [ -z "$RELEASE" ]; then
  pip install --quiet "$ROOT[vision,voice]"
elif [ -d "$RELEASE" ]; then
  pip install --quiet --find-links "$RELEASE" "flow-agent[vision,voice]"
elif [ -f "$RELEASE" ]; then
  pip install --quiet "flow-agent[vision,voice] @ file://$(cd "$(dirname "$RELEASE")" && pwd)/$(basename "$RELEASE")"
else
  pip install --quiet "flow-agent[vision,voice] @ $RELEASE"
fi
flow version

say "3/6 Native observer helper"
if [ -z "${FLOW_MACOS_HELPER:-}" ] && [ "$(uname -s)" = "Darwin" ]; then
  if command -v swift >/dev/null 2>&1; then
    FLOW_HELPER_INSTALL_DIR="$VENV/bin" "$ROOT/scripts/build-macos-helper.sh" \
      && export FLOW_MACOS_HELPER="$VENV/bin/flow-macos-observer" \
      || echo "helper build failed; the screencapture fallback will be used" >&2
  else
    echo "swift not found; the screencapture fallback will be used (main display only)" >&2
  fi
fi

say "4/6 Screen Recording permission"
if [ "$(uname -s)" = "Darwin" ]; then
  flow observer permissions --request || true
  echo "If denied: System Settings > Privacy & Security > Screen Recording, enable your terminal, then restart it."
  pause "Press Enter when Screen Recording is granted..."
fi

say "5/6 Models"
flow models status || true
echo "Install missing models with: flow models install   (about 6 GB, one time)"

if [ "$INTERACTIVE" = "1" ]; then
  say "Guided scenarios need a live FLOW session"
  export FLOW_DATA_DIR="${FLOW_DATA_DIR:-$PWD/.local-runs}"
  cat <<TXT
In ANOTHER terminal (same FLOW_DATA_DIR=$FLOW_DATA_DIR, venv activated):
  flow config exclude-app Messages      # or any app you will use for the privacy check
  flow start --goal "Fix JWT authentication tests"
and keep FLOW's observer/voice loop running. This script only reads its local sqlite store.
TXT
  pause "Press Enter when the session is running..."
fi

say "6/6 flow validate macos"
ARGS=(validate macos --output "$ARTIFACT")
[ "$INTERACTIVE" = "1" ] || ARGS+=(--non-interactive)
[ "${FLOW_VALIDATE_ALLOW_PARTIAL:-0}" = "1" ] || ARGS+=(--strict)
# shellcheck disable=SC2206
[ -z "${FLOW_VALIDATE_ARGS:-}" ] || ARGS+=(${FLOW_VALIDATE_ARGS})
set +e
flow "${ARGS[@]}"
STATUS=$?
set -e

echo
echo "Artifact: $ARTIFACT"
python - "$ARTIFACT" <<'PY' || true
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except (OSError, ValueError) as exc:
    print(f"no artifact: {exc}"); raise SystemExit(0)
print("overall:", data.get("overall"), data.get("summary"))
bad = [k for k, v in data.items() if isinstance(v, dict) and v.get("status") == "failed"]
bad += [f"scenario:{k}" for k, v in data.get("scenarios", {}).items() if v.get("status") == "failed"]
if bad:
    print("FAILED:", ", ".join(bad))
PY
if [ "$STATUS" -ne 0 ]; then
  echo "Validation did not fully pass (exit $STATUS). See the artifact for per-check evidence." >&2
fi
exit "$STATUS"
