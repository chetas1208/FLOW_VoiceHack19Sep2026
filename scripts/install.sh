#!/bin/sh
set -eu

PACKAGE="${FLOW_PACKAGE:-flow-agent}"
VERSION="${FLOW_VERSION:-}"
PYTHON="${PYTHON:-python3}"

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) echo "FLOW installer supports macOS and Linux development hosts only." >&2; exit 1 ;;
esac

command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python 3 is required." >&2; exit 1; }
"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("FLOW requires Python 3.11 or newer.")
PY

if command -v pipx >/dev/null 2>&1; then
  if [ -n "$VERSION" ]; then pipx install --force "$PACKAGE==$VERSION"; else pipx install --force "$PACKAGE"; fi
  TARGET="$(command -v flow || true)"
else
  BIN="$HOME/.local/bin"
  VENV="$HOME/.local/share/flow/venv"
  mkdir -p "$BIN" "$HOME/.local/share/flow"
  "$PYTHON" -m venv "$VENV"
  "$VENV/bin/python" -m pip install --upgrade pip >/dev/null
  if [ -n "$VERSION" ]; then "$VENV/bin/pip" install "$PACKAGE==$VERSION"; else "$VENV/bin/pip" install "$PACKAGE"; fi
  ln -sf "$VENV/bin/flow" "$BIN/flow"
  TARGET="$BIN/flow"
fi

echo "FLOW installed successfully."
echo "Binary  $TARGET"
echo "Next:   flow login"
