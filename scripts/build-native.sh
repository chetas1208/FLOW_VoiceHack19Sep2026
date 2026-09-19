#!/usr/bin/env bash
# Build the optional macOS ScreenCaptureKit helper.
# FLOW runs fine without it: screenshot capture is simply unavailable and the
# analyzer falls back to clearly-labelled metadata-only analysis.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "FlowCapture is macOS-only; skipping native build on $(uname -s)." >&2
  exit 0
fi
if ! command -v swiftc >/dev/null 2>&1; then
  echo "swiftc not found (install Xcode Command Line Tools: xcode-select --install); skipping native build." >&2
  exit 0
fi

mkdir -p native/bin
echo "Building native/bin/FlowCapture …"
swiftc -O \
  -target arm64-apple-macos14.0 \
  -framework ScreenCaptureKit -framework AppKit -framework CoreGraphics -framework UniformTypeIdentifiers \
  -o native/bin/FlowCapture native/FlowCapture.swift 2>&1 | sed 's/^/  /' || {
    echo "Native build failed. FLOW will run without screenshot capture." >&2
    exit 0
  }
echo "✓ native/bin/FlowCapture"
native/bin/FlowCapture permission || true
