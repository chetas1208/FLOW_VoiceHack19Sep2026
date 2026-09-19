#!/bin/sh
# Build FLOW release artifacts (no PyPI): the embedded web UI, then sdist + wheel + SHA256SUMS + latest.json +
# install.sh, then verify the wheel in a clean virtualenv.
#
#   scripts/build-release.sh [--out DIR] [--no-verify] [--no-isolation] [--no-frontend] [--require-frontend]
#
# The frontend (web/ -> `npm ci && npm run build:embedded`) is copied into services/flow/server/ui_dist so it ships
# in the wheel and the daemon can serve it at /ui. If web/ is not ready or npm is missing the wheel is built without
# it and a warning is printed; pass --require-frontend (use it for real releases) to make that an error.
#
# Upload the contents of DIR to a GitHub release (or any static host); installers fetch
# <FLOW_RELEASE_URL>/latest.json, the wheel and SHA256SUMS, and verify the checksum before installing.
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/dist"
VERIFY=1
ISOLATION=1
FRONTEND=1
REQUIRE_FRONTEND=0
PYTHON="${PYTHON:-python3}"

while [ $# -gt 0 ]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --out=*) OUT="${1#--out=}"; shift ;;
    --no-verify) VERIFY=0; shift ;;
    --no-isolation) ISOLATION=0; shift ;;
    --no-frontend) FRONTEND=0; shift ;;
    --require-frontend) REQUIRE_FRONTEND=1; shift ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "build-release: unknown argument $1" >&2; exit 2 ;;
  esac
done

command -v "$PYTHON" >/dev/null 2>&1 || PYTHON=python
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
cd "$ROOT"

UI_DIST="$ROOT/services/flow/server/ui_dist"
frontend_skipped() {
  if [ "$REQUIRE_FRONTEND" = 1 ]; then echo "build-release: frontend required but $1" >&2; exit 1; fi
  echo "warning: building WITHOUT the embedded web UI ($1)" >&2
}
if [ "$FRONTEND" = 1 ]; then
  echo "==> building the embedded web UI"
  if [ ! -f "$ROOT/web/package.json" ]; then
    frontend_skipped "web/package.json not found"
  elif ! command -v npm >/dev/null 2>&1; then
    frontend_skipped "npm is not installed"
  elif ! "$PYTHON" -c 'import json,sys; sys.exit(0 if "build:embedded" in json.load(open(sys.argv[1])).get("scripts", {}) else 1)' "$ROOT/web/package.json"; then
    frontend_skipped "web/package.json has no build:embedded script yet"
  else
    if ( cd "$ROOT/web" && npm ci --no-audit --no-fund && npm run build:embedded ); then
      BUILT=""
      for candidate in "${FLOW_UI_BUILD_DIR:-}" "$ROOT/web/dist-embedded" "$ROOT/web/dist"; do
        if [ -n "$candidate" ] && [ -f "$candidate/index.html" ]; then BUILT="$candidate"; break; fi
      done
      if [ -z "$BUILT" ]; then
        frontend_skipped "build:embedded produced no index.html (looked in web/dist-embedded and web/dist; set FLOW_UI_BUILD_DIR)"
      else
        rm -rf "$UI_DIST"
        mkdir -p "$UI_DIST"
        cp -R "$BUILT"/. "$UI_DIST"/
        echo "embedded UI: $BUILT -> ${UI_DIST#$ROOT/}"
      fi
    else
      frontend_skipped "npm build failed"
    fi
  fi
fi

echo "==> cleaning previous artifacts in $OUT"
rm -f "$OUT"/flow_agent-* "$OUT"/SHA256SUMS "$OUT"/latest.json "$OUT"/install.sh

echo "==> building sdist + wheel"
if [ "$ISOLATION" = 1 ]; then
  "$PYTHON" -m build --sdist --wheel --outdir "$OUT" "$ROOT"
else
  "$PYTHON" -m build --sdist --wheel --no-isolation --outdir "$OUT" "$ROOT"
fi
rm -rf "$ROOT/build"

echo "==> writing SHA256SUMS and latest.json"
"$PYTHON" - "$OUT" <<'PY'
import hashlib, json, sys, zipfile
from pathlib import Path

out = Path(sys.argv[1])
wheels = sorted(out.glob("flow_agent-*.whl"))
sdists = sorted(out.glob("flow_agent-*.tar.gz"))
if len(wheels) != 1 or len(sdists) != 1:
    raise SystemExit(f"expected exactly one wheel and one sdist in {out}, found {wheels} {sdists}")
wheel, sdist = wheels[0], sdists[0]

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

with zipfile.ZipFile(wheel) as archive:
    names = archive.namelist()
    metadata = next(n for n in names if n.endswith(".dist-info/METADATA"))
    fields = dict(line.split(": ", 1) for line in archive.read(metadata).decode().splitlines() if ": " in line)
    if "services/flow/cli.py" not in names:
        raise SystemExit("wheel is missing services/flow/cli.py")
    forbidden = [n for n in names if n.endswith((".pem", ".key", ".env", ".sqlite3")) or "/tests/" in n
                 or n.startswith(("services/flowcloud/", "experiments/"))]
    if forbidden:
        raise SystemExit(f"wheel contains files that must not ship: {forbidden[:5]}")
    ui_built = (out.parent / "services/flow/server/ui_dist/index.html").exists() if False else None
    has_ui = "services/flow/server/ui_dist/index.html" in names
    print("embedded web UI in wheel: " + ("yes" if has_ui else "NO (built without frontend)"))

digest = sha256(wheel)
(out / "SHA256SUMS").write_text(f"{digest}  {wheel.name}\n{sha256(sdist)}  {sdist.name}\n")
latest = {"version": fields["Version"], "wheel": wheel.name, "sha256": digest,
          "requires_python": fields.get("Requires-Python", ">=3.11")}
(out / "latest.json").write_text(json.dumps(latest, indent=2) + "\n")
print(f"version {latest['version']}  wheel {wheel.name}  sha256 {digest}")
PY
cp "$ROOT/scripts/install.sh" "$OUT/install.sh"
chmod 0755 "$OUT/install.sh"

if [ "$VERIFY" = 1 ]; then
  echo "==> verifying wheel in a clean virtualenv"
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/flow-release-verify.XXXXXX")"
  trap 'rm -rf "$WORK"' EXIT INT TERM
  "$PYTHON" -m venv "$WORK/venv"
  WHEEL="$(ls "$OUT"/flow_agent-*.whl)"
  "$WORK/venv/bin/python" -m pip install --quiet --disable-pip-version-check "$WHEEL"
  mkdir -p "$WORK/home" "$WORK/cwd"
  # Run from an unrelated cwd with an isolated HOME so nothing can resolve to the repository checkout.
  cd "$WORK/cwd"
  export HOME="$WORK/home" PYTHONPATH="" FLOW_CONFIG_DIR="$WORK/home/.flow"
  "$WORK/venv/bin/flow" --help >/dev/null
  VERSION_OUT="$("$WORK/venv/bin/flow" version)"
  EXPECTED="$("$PYTHON" -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$OUT/latest.json")"
  [ "$VERSION_OUT" = "$EXPECTED" ] || { echo "flow version '$VERSION_OUT' != wheel version '$EXPECTED'" >&2; exit 1; }
  "$WORK/venv/bin/python" - "$ROOT" <<'PY'
import importlib, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
for name in ("services.flow.cli", "services.flowcloud"):
    module = importlib.import_module(name)
    location = pathlib.Path(module.__file__).resolve()
    if root in location.parents or "site-packages" not in location.parts:
        raise SystemExit(f"{name} imported from {location}, not the installed wheel")
print("imports resolve to site-packages")
PY
  echo "verified: flow --help, flow version = $VERSION_OUT"
fi

echo "==> release artifacts in $OUT"
ls -1 "$OUT"
