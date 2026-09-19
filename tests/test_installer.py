"""End-to-end tests for scripts/install.sh against a locally built release directory (no PyPI for FLOW itself)."""

from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "scripts" / "install.sh"
BUILD_SH = ROOT / "scripts" / "build-release.sh"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX installer")


def run(cmd, *, env=None, cwd=None, stdin=None, timeout=600):
    return subprocess.run(cmd, env=env, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="module")
def release(tmp_path_factory) -> Path:
    """A real release directory: sdist, wheel, SHA256SUMS, latest.json, install.sh."""
    if importlib_missing("build"):
        pytest.skip("the `build` package is required to build a release")
    out = tmp_path_factory.mktemp("release")
    env = {**os.environ, "PYTHON": sys.executable}
    flags = ["--no-verify", "--no-frontend"]
    proc = run(["sh", str(BUILD_SH), "--out", str(out), *flags, "--no-isolation"], env=env, cwd=ROOT)
    if proc.returncode != 0:  # fall back to an isolated build (needs network for setuptools)
        proc = run(["sh", str(BUILD_SH), "--out", str(out), *flags], env=env, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out


def importlib_missing(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is None


@pytest.fixture(scope="module")
def wheelhouse(release, tmp_path_factory) -> Path:
    """Dependencies of the wheel, downloaded once so every install runs offline via FLOW_PIP_ARGS."""
    house = tmp_path_factory.mktemp("wheelhouse")
    wheel = next(release.glob("flow_agent-*.whl"))
    proc = run([sys.executable, "-m", "pip", "download", "--quiet", "--dest", str(house), str(wheel)])
    if proc.returncode != 0:
        pytest.skip(f"cannot download FLOW dependencies (offline?): {proc.stderr[-300:]}")
    return house


@pytest.fixture()
def home(tmp_path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def installer_env(home: Path, release_url, wheelhouse: Path | None, **extra) -> dict:
    env = {
        "PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(home.parent),
        "PYTHON": sys.executable, "FLOW_INSTALL_METHOD": "venv", "FLOW_RELEASE_URL": str(release_url),
        "PIP_CONFIG_FILE": os.devnull, "LANG": "C.UTF-8",
    }
    if wheelhouse is not None:
        env["FLOW_PIP_ARGS"] = f"--no-index --find-links {wheelhouse}"
    env.update({k: str(v) for k, v in extra.items()})
    return env


def latest(release: Path) -> dict:
    return json.loads((release / "latest.json").read_text())


def flow_bin(home: Path) -> Path:
    return home / ".local" / "bin" / "flow"


def flow(home: Path, *args: str):
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "FLOW_CONFIG_DIR": str(home / ".config" / "flow")}
    return run([str(flow_bin(home)), *args], env=env, cwd=home)


# ------------------------------------------------------------------------------- release artifacts


def test_release_metadata_is_consistent(release):
    meta = latest(release)
    assert set(meta) >= {"version", "wheel", "sha256"}
    wheel = release / meta["wheel"]
    assert wheel.is_file()
    import hashlib
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == meta["sha256"]
    sums = {line.split(None, 1)[1].strip(): line.split(None, 1)[0] for line in (release / "SHA256SUMS").read_text().splitlines()}
    assert sums[meta["wheel"]] == meta["sha256"]
    assert meta["sha256"] in (release / "SHA256SUMS").read_text()
    assert (release / "install.sh").read_text() == INSTALL_SH.read_text()


# ------------------------------------------------------------------------------- happy path


def test_install_end_to_end_is_idempotent_and_uninstallable(release, wheelhouse, home):
    env = installer_env(home, release, wheelhouse)
    proc = run(["sh", str(INSTALL_SH)], env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Checksum verified" in proc.stdout
    assert "flow setup" in proc.stdout and "flow models install" in proc.stdout
    assert "flow login" not in proc.stdout  # no accounts; nothing is downloaded by the installer
    assert "not on your PATH" in proc.stderr  # ~/.local/bin is not on PATH in the test env; rc files untouched

    link = flow_bin(home)
    assert link.is_symlink() and str(home / ".local" / "share" / "flow" / "venv") in os.readlink(link)
    version = latest(release)["version"]
    assert flow(home, "version").stdout.strip() == version
    assert flow(home, "--help").returncode == 0

    # No shell startup file was created or modified (toolchain dirs such as .cache/.rustup may appear from pip).
    names = {p.name for p in home.iterdir()}
    assert ".local" in names
    assert not names & {".bashrc", ".zshrc", ".profile", ".bash_profile", ".zprofile", ".zshenv", ".config"}

    # Re-running upgrades in place: still one venv, no leftovers, still working.
    again = run(["sh", str(INSTALL_SH)], env=env)
    assert again.returncode == 0, again.stdout + again.stderr
    assert sorted(p.name for p in (home / ".local" / "share" / "flow").iterdir()) == ["venv"]
    assert flow(home, "version").stdout.strip() == version

    # Uninstall keeps user configuration and is itself idempotent.
    config = home / ".config" / "flow"
    config.mkdir(parents=True)
    (config / "keep.json").write_text("{}")
    gone = run(["sh", str(INSTALL_SH), "--uninstall"], env=env)
    assert gone.returncode == 0, gone.stderr
    assert not link.exists() and not link.is_symlink()
    assert not (home / ".local" / "share" / "flow" / "venv").exists()
    assert (config / "keep.json").exists()
    assert run(["sh", str(INSTALL_SH), "--uninstall"], env=env).returncode == 0


def test_piped_install_via_file_url_and_curl_from_local_server(release, wheelhouse, home):
    """`cat install.sh | sh` (like `curl | sh`) with a file:// release, then the same release over local HTTP."""
    env = installer_env(home, f"file://{release}", wheelhouse)
    proc = run(["sh"], env=env, stdin=INSTALL_SH.read_text())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert flow(home, "version").stdout.strip() == latest(release)["version"]
    assert run(["sh", "-s", "--", "--uninstall"], env=env, stdin=INSTALL_SH.read_text()).returncode == 0

    if not shutil.which("curl"):
        pytest.skip("curl not installed")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(release))
    handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        refused = run(["sh", str(INSTALL_SH)], env=installer_env(home, url, wheelhouse))
        assert refused.returncode != 0 and "plain http" in refused.stderr
        ok = run(["sh", str(INSTALL_SH)], env=installer_env(home, url, wheelhouse, FLOW_ALLOW_INSECURE="1"))
        assert ok.returncode == 0, ok.stdout + ok.stderr
        assert flow(home, "version").stdout.strip() == latest(release)["version"]
    finally:
        server.shutdown()


# ------------------------------------------------------------------------------- integrity failures


def _copy_release(release: Path, tmp_path: Path) -> Path:
    target = tmp_path / "tampered"
    shutil.copytree(release, target)
    return target


def test_tampered_wheel_is_rejected_and_nothing_is_installed(release, wheelhouse, home, tmp_path):
    bad = _copy_release(release, tmp_path)
    wheel = bad / latest(bad)["wheel"]
    wheel.write_bytes(wheel.read_bytes() + b"\0tampered")
    proc = run(["sh", str(INSTALL_SH)], env=installer_env(home, bad, wheelhouse))
    assert proc.returncode != 0
    assert "checksum mismatch" in proc.stderr
    assert not flow_bin(home).exists() and not flow_bin(home).is_symlink()
    assert not (home / ".local" / "share" / "flow").exists()


def test_tampered_wheel_leaves_existing_install_untouched(release, wheelhouse, home, tmp_path):
    env = installer_env(home, release, wheelhouse)
    assert run(["sh", str(INSTALL_SH)], env=env).returncode == 0
    before = flow(home, "version").stdout.strip()
    bad = _copy_release(release, tmp_path)
    wheel = bad / latest(bad)["wheel"]
    wheel.write_bytes(wheel.read_bytes() + b"x")
    proc = run(["sh", str(INSTALL_SH)], env=installer_env(home, bad, wheelhouse))
    assert proc.returncode != 0 and "checksum mismatch" in proc.stderr
    assert flow(home, "version").stdout.strip() == before


@pytest.mark.parametrize("mutate, message", [
    (lambda d: (d / "SHA256SUMS").write_text(f"{'0' * 64}  {latest(d)['wheel']}\n"), "checksum mismatch"),
    (lambda d: (d / "SHA256SUMS").write_text(f"{latest(d)['sha256']}  other.whl\n"), "not listed in SHA256SUMS"),
    (lambda d: (d / "SHA256SUMS").unlink(), "SHA256SUMS not found"),
    (lambda d: (d / "latest.json").write_text(json.dumps({**latest(d), "sha256": "f" * 64})), "checksum mismatch"),
    (lambda d: (d / "latest.json").write_text(json.dumps({**latest(d), "wheel": "../evil.whl"})), "malformed"),
    (lambda d: (d / "latest.json").write_text(json.dumps({**latest(d), "sha256": "nothex"})), "malformed"),
    (lambda d: (d / "latest.json").write_text("not json"), "malformed"),
])
def test_inconsistent_metadata_is_rejected(release, wheelhouse, home, tmp_path, mutate, message):
    bad = _copy_release(release, tmp_path)
    mutate(bad)
    proc = run(["sh", str(INSTALL_SH)], env=installer_env(home, bad, wheelhouse))
    assert proc.returncode != 0
    assert message in proc.stderr
    assert not flow_bin(home).exists() and not flow_bin(home).is_symlink()


# ------------------------------------------------------------------------------- argument / environment checks


def test_version_pin_mismatch_aborts(release, wheelhouse, home):
    proc = run(["sh", str(INSTALL_SH)], env=installer_env(home, release, wheelhouse, FLOW_VERSION="99.0.0"))
    assert proc.returncode != 0 and "requested version 99.0.0" in proc.stderr
    assert not (home / ".local").exists()


def test_invalid_extras_and_method_are_rejected(release, wheelhouse, home):
    proc = run(["sh", str(INSTALL_SH)], env=installer_env(home, release, wheelhouse, FLOW_EXTRAS="vision;rm -rf /"))
    assert proc.returncode != 0 and "FLOW_EXTRAS" in proc.stderr
    proc = run(["sh", str(INSTALL_SH)], env=installer_env(home, release, wheelhouse, FLOW_INSTALL_METHOD="magic"))
    assert proc.returncode != 0 and "FLOW_INSTALL_METHOD" in proc.stderr


def test_missing_python_is_reported(release, home, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("uname",):
        (bin_dir / tool).symlink_to(shutil.which(tool))
    env = installer_env(home, release, None)
    env.pop("PYTHON")
    env["PATH"] = str(bin_dir)
    proc = run([shutil.which("sh"), str(INSTALL_SH)], env=env)
    assert proc.returncode != 0 and "Python 3.11 or newer is required" in proc.stderr


def test_unknown_release_location_and_bad_option(release, home, tmp_path):
    proc = run(["sh", str(INSTALL_SH)], env=installer_env(home, tmp_path / "missing", None))
    assert proc.returncode != 0 and "FLOW_RELEASE_URL" in proc.stderr
    proc = run(["sh", str(INSTALL_SH), "--bogus"], env=installer_env(home, release, None))
    assert proc.returncode != 0 and "unknown option" in proc.stderr
    assert run(["sh", str(INSTALL_SH), "--help"], env=installer_env(home, release, None)).returncode == 0


def test_installer_never_touches_shell_rc_files_or_uses_sudo():
    code = [line for line in INSTALL_SH.read_text().splitlines() if not line.lstrip().startswith("#")]
    text = "\n".join(code)
    import re
    assert not re.search(r"(^|[\s;&|(])sudo\s", text.replace("No sudo is used", "")), "installer must not call sudo"
    for forbidden in (".bashrc", ".zshrc", ".bash_profile", ">> \"$HOME", ">> ~"):
        assert forbidden not in text, forbidden
    assert "pypi.org" not in text.lower()
