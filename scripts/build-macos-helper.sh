#!/bin/sh
# Build the FLOW macOS observer helper (Swift, ScreenCaptureKit). macOS 13+ with Xcode CLT.
# Output: native/macos-observer/.build/release/flow-macos-observer
# Optional: FLOW_HELPER_INSTALL_DIR=<dir> copies the binary there (e.g. ~/.local/bin).
# STATUS: IMPLEMENTED_ENVIRONMENT_UNVERIFIED (never run on macOS by the author).
set -eu

if [ "$(uname -s)" != "Darwin" ]; then
  echo "build-macos-helper: this helper builds only on macOS (found $(uname -s))." >&2
  exit 2
fi
command -v swift >/dev/null 2>&1 || {
  echo "build-macos-helper: swift not found. Install Xcode or run: xcode-select --install" >&2
  exit 2
}

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE="$ROOT/native/macos-observer"
swift build -c release --package-path "$PACKAGE"
BINARY="$PACKAGE/.build/release/flow-macos-observer"
[ -x "$BINARY" ] || { echo "build-macos-helper: expected binary missing: $BINARY" >&2; exit 1; }

# Ad-hoc sign so macOS attributes the Screen Recording grant to a stable identity.
codesign --force --sign - "$BINARY" >/dev/null 2>&1 || echo "build-macos-helper: ad-hoc codesign skipped" >&2

if [ -n "${FLOW_HELPER_INSTALL_DIR:-}" ]; then
  mkdir -p "$FLOW_HELPER_INSTALL_DIR"
  cp "$BINARY" "$FLOW_HELPER_INSTALL_DIR/flow-macos-observer"
  BINARY="$FLOW_HELPER_INSTALL_DIR/flow-macos-observer"
fi

"$BINARY" version
echo "Helper built: $BINARY"
echo "Use it with: export FLOW_MACOS_HELPER=\"$BINARY\""
