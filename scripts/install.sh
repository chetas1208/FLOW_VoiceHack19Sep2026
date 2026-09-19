#!/bin/sh
# FLOW installer. FLOW is not published on PyPI; it is installed from release artifacts.
#
#   curl -fsSL https://github.com/chetas1208/FLOW_VoiceHack19Sep2026/releases/latest/download/install.sh | sh
#   curl -fsSL <url>/install.sh | sh -s -- --uninstall
#
# What it does: detects OS/arch/Python (>= 3.11), downloads latest.json + the wheel + SHA256SUMS, VERIFIES the
# sha256 (aborts on mismatch, before touching any existing install), then installs with pipx when available or
# into a private virtualenv (~/.local/share/flow/venv) with a symlink in ~/.local/bin. No sudo, no shell rc edits,
# safe to re-run (upgrade/reinstall). It installs code only: models are never downloaded (see `flow models install`).
#
# Environment:
#   FLOW_RELEASE_URL     release location: https://... (default: GitHub latest release), file:///dir or a directory
#   FLOW_VERSION         install a specific version (default: whatever latest.json says)
#   FLOW_EXTRAS          pip extras, e.g. "vision,voice"
#   FLOW_INSTALL_METHOD  auto (default) | pipx | venv
#   FLOW_INSTALL_DIR     private install root for the venv method (default ~/.local/share/flow)
#   FLOW_BIN_DIR         where the `flow` symlink goes for the venv method (default ~/.local/bin)
#   FLOW_PIP_ARGS        extra pip arguments, e.g. "--index-url https://mirror.example/simple"
#   FLOW_ALLOW_INSECURE  set to 1 to allow a plain http:// release URL (never for production)
#   PYTHON               interpreter to use (default: first python >= 3.11 on PATH)
#
# Options: --uninstall   remove FLOW (keeps ~/.config/flow), --help
#
# The body lives in main() and runs last so `curl | sh` never executes a half-downloaded script and child
# processes cannot swallow the rest of the script from stdin.

set -eu

DEFAULT_RELEASE_URL="https://github.com/chetas1208/FLOW_VoiceHack19Sep2026/releases/latest/download"
DEFAULT_RELEASE_BASE="https://github.com/chetas1208/FLOW_VoiceHack19Sep2026/releases/download"
PACKAGE="flow-agent"

say() { printf '%s\n' "$*"; }
warn() { printf 'flow-install: warning: %s\n' "$*" >&2; }
die() { printf 'flow-install: error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
FLOW installer (installs from release artifacts; FLOW is not on PyPI)

  curl -fsSL <release-url>/install.sh | sh
  curl -fsSL <release-url>/install.sh | sh -s -- --uninstall

Options: --uninstall (keeps ~/.config/flow), --version X.Y.Z, --help
Environment: FLOW_RELEASE_URL (https://, file:///dir or a directory), FLOW_VERSION, FLOW_EXTRAS (e.g. vision,voice),
  FLOW_INSTALL_METHOD (auto|pipx|venv), FLOW_INSTALL_DIR, FLOW_BIN_DIR, FLOW_PIP_ARGS, FLOW_ALLOW_INSECURE, PYTHON
The sha256 of the wheel is verified against latest.json and SHA256SUMS before anything is installed.
No sudo is used and shell startup files are never modified.
USAGE
}

find_python() {
  for candidate in "${PYTHON:-}" python3.13 python3.12 python3.11 python3 python; do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1 </dev/null; then
        command -v "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

# fetch NAME DEST : copy from a local release directory or download over HTTPS.
fetch() {
  _name="$1"; _dest="$2"
  case "$RELEASE_KIND" in
    dir)
      [ -f "$RELEASE_SRC/$_name" ] || die "$RELEASE_SRC/$_name not found"
      cp "$RELEASE_SRC/$_name" "$_dest"
      ;;
    http)
      if command -v curl >/dev/null 2>&1; then
        if [ "${FLOW_ALLOW_INSECURE:-0}" = 1 ]; then
          curl -fsSL --retry 3 --connect-timeout 15 -o "$_dest" "$RELEASE_SRC/$_name" </dev/null \
            || die "download failed: $RELEASE_SRC/$_name"
        else
          curl -fsSL --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 15 -o "$_dest" "$RELEASE_SRC/$_name" </dev/null \
            || die "download failed: $RELEASE_SRC/$_name"
        fi
      elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$_dest" "$RELEASE_SRC/$_name" </dev/null || die "download failed: $RELEASE_SRC/$_name"
      else
        die "curl or wget is required"
      fi
      ;;
  esac
}

resolve_release() {
  _url="${FLOW_RELEASE_URL:-}"
  if [ -z "$_url" ]; then
    if [ -n "${FLOW_VERSION:-}" ]; then
      _url="$DEFAULT_RELEASE_BASE/v${FLOW_VERSION#v}"
    else
      _url="$DEFAULT_RELEASE_URL"
    fi
  fi
  _url="${_url%/}"
  case "$_url" in
    file://*) RELEASE_KIND=dir; RELEASE_SRC="${_url#file://}" ;;
    https://*) RELEASE_KIND=http; RELEASE_SRC="$_url" ;;
    http://*)
      [ "${FLOW_ALLOW_INSECURE:-0}" = 1 ] || die "refusing plain http:// release URL (set FLOW_ALLOW_INSECURE=1 to override)"
      RELEASE_KIND=http; RELEASE_SRC="$_url" ;;
    *)
      [ -d "$_url" ] || die "FLOW_RELEASE_URL must be https://, file:// or an existing directory (got: $_url)"
      RELEASE_KIND=dir; RELEASE_SRC="$_url" ;;
  esac
  if [ "$RELEASE_KIND" = dir ]; then
    [ -d "$RELEASE_SRC" ] || die "release directory $RELEASE_SRC does not exist"
    RELEASE_SRC="$(cd "$RELEASE_SRC" && pwd)"
  fi
}

# Print "version wheel sha256" from latest.json, validating each field.
parse_latest() {
  "$PY" - "$1" <<'PYEOF' || return 1
import json, re, sys
data = json.load(open(sys.argv[1]))
version, wheel, digest = str(data["version"]), str(data["wheel"]), str(data["sha256"]).lower()
if not re.fullmatch(r"[0-9A-Za-z.!+_-]+", version):
    raise SystemExit("latest.json: invalid version")
if not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", wheel):
    raise SystemExit("latest.json: invalid wheel file name")
if not re.fullmatch(r"[0-9a-f]{64}", digest):
    raise SystemExit("latest.json: invalid sha256")
print(version, wheel, digest)
PYEOF
}

sha256_of() {
  "$PY" -c 'import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
print(h.hexdigest())' "$1" </dev/null
}

# Look up NAME in a sha256sum-style file.
sums_entry() {
  "$PY" - "$1" "$2" <<'PYEOF'
import sys
for line in open(sys.argv[1]):
    parts = line.split(None, 1)
    if len(parts) == 2 and parts[1].strip().lstrip("*") == sys.argv[2]:
        print(parts[0].lower())
        break
PYEOF
}

pipx_has_flow() {
  command -v pipx >/dev/null 2>&1 && pipx list --short 2>/dev/null </dev/null | grep -q "^$PACKAGE "
}

remove_venv_install() {
  if [ -L "$BIN_DIR/flow" ]; then
    case "$(readlink "$BIN_DIR/flow")" in
      "$INSTALL_DIR"/*) rm -f "$BIN_DIR/flow"; say "removed $BIN_DIR/flow" ;;
    esac
  fi
  if [ -d "$INSTALL_DIR/venv" ]; then
    rm -rf "$INSTALL_DIR/venv"
    say "removed $INSTALL_DIR/venv"
  fi
  rm -rf "$INSTALL_DIR/venv.new" "$INSTALL_DIR/venv.old"
  rmdir "$INSTALL_DIR" 2>/dev/null || true
}

do_uninstall() {
  _found=0
  if pipx_has_flow; then
    pipx uninstall "$PACKAGE" </dev/null && _found=1
  fi
  if [ -d "$INSTALL_DIR/venv" ] || [ -L "$BIN_DIR/flow" ]; then
    _found=1
    remove_venv_install
  fi
  if [ "$_found" = 1 ]; then say "FLOW uninstalled. Your settings in ~/.config/flow were kept."; else say "FLOW is not installed; nothing to do."; fi
}

main() {
  ACTION=install
  while [ $# -gt 0 ]; do
    case "$1" in
      --uninstall) ACTION=uninstall ;;
      --help|-h) usage; return 0 ;;
      --version) shift; [ $# -gt 0 ] || die "--version needs a value"; FLOW_VERSION="$1" ;;
      *) die "unknown option: $1 (try --help)" ;;
    esac
    shift
  done

  [ -n "${HOME:-}" ] || die "HOME is not set"
  INSTALL_DIR="${FLOW_INSTALL_DIR:-$HOME/.local/share/flow}"
  BIN_DIR="${FLOW_BIN_DIR:-$HOME/.local/bin}"
  METHOD="${FLOW_INSTALL_METHOD:-auto}"
  EXTRAS="${FLOW_EXTRAS:-}"
  case "$METHOD" in auto|pipx|venv) ;; *) die "FLOW_INSTALL_METHOD must be auto, pipx or venv" ;; esac

  if [ "$ACTION" = uninstall ]; then do_uninstall; return 0; fi

  OS="$(uname -s)"; ARCH="$(uname -m)"
  case "$OS" in Darwin|Linux) ;; *) die "unsupported OS $OS (FLOW supports macOS and Linux)" ;; esac
  case "$ARCH" in x86_64|amd64|arm64|aarch64) ;; *) warn "untested architecture $ARCH" ;; esac
  case "$EXTRAS" in *[!A-Za-z0-9_.,-]*) die "FLOW_EXTRAS may only contain letters, digits, ',', '-', '_' and '.'" ;; esac

  PY="$(find_python)" || die "Python 3.11 or newer is required (set PYTHON=/path/to/python)"
  PYVER="$("$PY" -c 'import platform; print(platform.python_version())' </dev/null)"
  say "FLOW installer: $OS/$ARCH, Python $PYVER ($PY)"

  resolve_release
  TMP="$(mktemp -d "${TMPDIR:-/tmp}/flow-install.XXXXXX")" || die "cannot create temp dir"
  trap 'rm -rf "$TMP"' EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM

  say "Fetching release metadata from $RELEASE_SRC"
  fetch latest.json "$TMP/latest.json"
  fetch SHA256SUMS "$TMP/SHA256SUMS"
  LATEST="$(parse_latest "$TMP/latest.json")" || die "latest.json is malformed"
  VERSION="${LATEST%% *}"; REST="${LATEST#* }"; WHEEL="${REST%% *}"; EXPECTED="${REST#* }"
  if [ -n "${FLOW_VERSION:-}" ] && [ "$VERSION" != "${FLOW_VERSION#v}" ]; then
    die "requested version ${FLOW_VERSION#v} but the release provides $VERSION"
  fi

  say "Downloading $WHEEL"
  fetch "$WHEEL" "$TMP/$WHEEL"

  ACTUAL="$(sha256_of "$TMP/$WHEEL")"
  LISTED="$(sums_entry "$TMP/SHA256SUMS" "$WHEEL")"
  [ -n "$LISTED" ] || die "$WHEEL is not listed in SHA256SUMS; refusing to install"
  if [ "$ACTUAL" != "$EXPECTED" ] || [ "$ACTUAL" != "$LISTED" ]; then
    die "checksum mismatch for $WHEEL (downloaded $ACTUAL, latest.json $EXPECTED, SHA256SUMS $LISTED); nothing was installed"
  fi
  say "Checksum verified: sha256 $ACTUAL"

  SPEC="$TMP/$WHEEL"
  [ -z "$EXTRAS" ] || SPEC="$TMP/$WHEEL[$EXTRAS]"

  if [ "$METHOD" = auto ]; then
    if command -v pipx >/dev/null 2>&1; then METHOD=pipx; else METHOD=venv; fi
  fi
  [ "$METHOD" != pipx ] || command -v pipx >/dev/null 2>&1 || die "FLOW_INSTALL_METHOD=pipx but pipx is not installed"

  say "Installing FLOW $VERSION with $METHOD (dependencies come from your configured package index)"
  if [ "$METHOD" = pipx ]; then
    # shellcheck disable=SC2086
    pipx install --force --python "$PY" ${FLOW_PIP_ARGS:+--pip-args="$FLOW_PIP_ARGS"} "$SPEC" </dev/null \
      || die "pipx install failed"
    FLOW_BIN="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null </dev/null || true)"
    [ -n "$FLOW_BIN" ] || FLOW_BIN="$HOME/.local/bin"
    TARGET="$FLOW_BIN/flow"
    [ -x "$TARGET" ] || die "pipx did not create $TARGET"
    # A previous private-venv install would now shadow or duplicate the pipx one.
    if [ -d "$INSTALL_DIR/venv" ]; then remove_venv_install; fi
    BIN_FOR_PATH="$FLOW_BIN"
  else
    mkdir -p "$INSTALL_DIR" "$BIN_DIR"
    # Virtualenv scripts embed their absolute path, so build in the final location. The previous install is
    # parked in venv.old and restored if anything below fails.
    rm -rf "$INSTALL_DIR/venv.old"
    [ ! -d "$INSTALL_DIR/venv" ] || mv "$INSTALL_DIR/venv" "$INSTALL_DIR/venv.old"
    rollback() {
      rm -rf "$INSTALL_DIR/venv"
      if [ -d "$INSTALL_DIR/venv.old" ]; then mv "$INSTALL_DIR/venv.old" "$INSTALL_DIR/venv"; fi
      die "$1; the previous installation (if any) was restored"
    }
    "$PY" -m venv "$INSTALL_DIR/venv" </dev/null || rollback "could not create a virtualenv (is the python venv module installed?)"
    # shellcheck disable=SC2086
    "$INSTALL_DIR/venv/bin/python" -m pip install --quiet --disable-pip-version-check ${FLOW_PIP_ARGS:-} "$SPEC" </dev/null \
      || rollback "pip install failed"
    NEW_VERSION="$("$INSTALL_DIR/venv/bin/flow" version 2>/dev/null </dev/null || true)"
    [ "$NEW_VERSION" = "$VERSION" ] || rollback "installed flow reported version '$NEW_VERSION', expected '$VERSION'"
    rm -rf "$INSTALL_DIR/venv.old"
    ln -sfn "$INSTALL_DIR/venv/bin/flow" "$BIN_DIR/flow"
    TARGET="$BIN_DIR/flow"
    BIN_FOR_PATH="$BIN_DIR"
    if pipx_has_flow; then pipx uninstall "$PACKAGE" </dev/null >/dev/null 2>&1 || true; fi
  fi

  INSTALLED="$("$TARGET" version </dev/null 2>/dev/null)" || die "installed flow failed to run: $TARGET version"
  [ "$INSTALLED" = "$VERSION" ] || die "installed flow reports '$INSTALLED', expected '$VERSION'"

  say ""
  say "FLOW $INSTALLED installed successfully."
  say "  binary   $TARGET"
  case ":$PATH:" in
    *":$BIN_FOR_PATH:"*) ;;
    *)
      warn "$BIN_FOR_PATH is not on your PATH. Add it yourself, for example:"
      say "           export PATH=\"$BIN_FOR_PATH:\$PATH\""
      ;;
  esac
  say ""
  say "Next steps:"
  say "  flow setup     guided first-run setup (permissions, optional local models, remote access)"
  say "  flow doctor    check your setup"
  say ""
  say "This installed FLOW's code only. No models were downloaded; install them when you want with:"
  say "  flow models install"
  if [ "$RELEASE_KIND" = http ]; then
    say "Uninstall:  curl -fsSL $RELEASE_SRC/install.sh | sh -s -- --uninstall"
  else
    say "Uninstall:  sh $RELEASE_SRC/install.sh --uninstall"
  fi
}

main "$@"
