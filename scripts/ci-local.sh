#!/bin/sh
# Local CI for FLOW (there are deliberately no GitHub Actions). Fails fast; run before every delivery.
#
#   scripts/ci-local.sh
#   FLOW_CI_SKIP="release,installer,frontend" scripts/ci-local.sh     # comma list of steps to skip
#
# Steps: compile, contracts, pytest, release (build + clean-venv wheel smoke test), installer, frontend, secrets.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null 2>&1 || PYTHON=python
SKIP=",${FLOW_CI_SKIP:-},"
cd "$ROOT"

skipped() { case "$SKIP" in *",$1,"*) echo "==> skipping $1 (FLOW_CI_SKIP)"; return 0 ;; esac; return 1; }
step() { echo; echo "==> $1"; }

# ---------------------------------------------------------------------------------------------- compile
if ! skipped compile; then
  step "compileall"
  dirs=""
  for d in services benchmarks contracts scripts tests; do [ -d "$d" ] && dirs="$dirs $d"; done
  # shellcheck disable=SC2086
  "$PYTHON" -m compileall -q $dirs
fi

# ------------------------------------------------------------------------------------------- contracts
if ! skipped contracts; then
  step "contract validation"
  "$PYTHON" scripts/validate_contracts.py
fi

# --------------------------------------------------------------------------------------------- pytest
if ! skipped pytest; then
  step "pytest tests/ (all product, contract and flow tests)"
  "$PYTHON" -m pytest tests -q --ignore=tests/test_installer.py
fi

# --------------------------------------------------------------------------------------------- release
if ! skipped release; then
  step "release build + clean-venv wheel smoke test"
  RELEASE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/flow-ci-release.XXXXXX")"
  trap 'rm -rf "$RELEASE_DIR"' EXIT INT TERM
  flags=""
  # A real release must ship the UI: require it whenever the frontend can be built here.
  if command -v npm >/dev/null 2>&1 && [ -f web/package.json ] && \
     "$PYTHON" -c 'import json,sys; sys.exit(0 if "build:embedded" in json.load(open("web/package.json")).get("scripts", {}) else 1)'; then
    flags="--require-frontend"
  fi
  # shellcheck disable=SC2086
  scripts/build-release.sh --out "$RELEASE_DIR" $flags
  (cd "$RELEASE_DIR" && "$PYTHON" - <<'PY'
import hashlib, json, pathlib
meta = json.load(open("latest.json"))
sums = dict(line.split()[::-1] for line in open("SHA256SUMS").read().splitlines())
digest = hashlib.sha256(pathlib.Path(meta["wheel"]).read_bytes()).hexdigest()
assert digest == meta["sha256"] == sums[meta["wheel"]], "latest.json / SHA256SUMS disagree with the wheel"
print("release metadata consistent:", meta["version"], digest[:16])
PY
  )
fi

# ------------------------------------------------------------------------------------------- installer
if ! skipped installer; then
  step "installer end-to-end tests (temp HOME, local release dir, tampered-wheel negative test)"
  "$PYTHON" -m pytest tests/test_installer.py -q
fi

# ------------------------------------------------------------------------------------------ frontend
if ! skipped frontend; then
  if [ -f web/package.json ] && command -v npm >/dev/null 2>&1; then
    step "frontend: typecheck + unit tests"
    (
      cd web
      [ -d node_modules ] || npm ci --no-audit --no-fund
      npm run --silent typecheck
      npm test --silent
    )
  else
    step "frontend: skipped (web/package.json or npm not available)"
  fi
fi

# ------------------------------------------------------------------------------------------- secrets
if ! skipped secrets; then
  step "secret scan (tracked + untracked, placeholders allowed)"
  PATTERNS='-----BEGIN ([A-Z]+ )?PRIVATE KEY-----|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,}|xox[baprs]-[A-Za-z0-9-]{10,}|sk-[A-Za-z0-9]{32,}|hf_[A-Za-z0-9]{34,}|AIza[0-9A-Za-z_-]{35}|eyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}|(api[_-]?key|secret|passw(or)?d|token|auth)[A-Za-z0-9_]*["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9+/_=.-]{24,}["'"'"']'
  ALLOWED='CHANGE_?ME|example|placeholder|dummy|fake|xxxx|YOUR_|<[A-Za-z_ -]+>|\$\{|\$\(|allowlist secret|os\.environ|getenv|not-a-real|test-only|redacted'
  EXCLUDES=':(exclude)web/package-lock.json :(exclude)*.lock :(exclude)experiments/*'
  # shellcheck disable=SC2086
  hits="$(git grep -I -n -i -E --untracked -e "$PATTERNS" -- . $EXCLUDES 2>/dev/null | grep -v -i -E "$ALLOWED" || true)"
  files="$(git ls-files -co --exclude-standard | grep -E '(^|/)\.env($|\.)|\.pem$|\.p12$|id_(rsa|ed25519)$|\.sqlite3?$' | grep -v -E '\.env\.example$' || true)"
  if [ -n "$hits" ] || [ -n "$files" ]; then
    [ -z "$hits" ] || { echo "possible secrets:" >&2; echo "$hits" >&2; }
    [ -z "$files" ] || { echo "files that must not be committed:" >&2; echo "$files" >&2; }
    echo "secret scan FAILED (add '# allowlist secret' to a deliberate fixture line)" >&2
    exit 1
  fi
  echo "no secrets found"
fi

echo
echo "ci-local: all steps passed"
