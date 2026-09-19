"""macOS observer tests. macOS itself is unavailable here, so every native call is mocked:
fake runners for the unit tests, and a real fake ``flow-macos-observer`` script for protocol tests.

IMPLEMENTED_ENVIRONMENT_UNVERIFIED: nothing in this file proves ScreenCaptureKit works on a Mac.
"""

import asyncio
import json
import os
import stat
import struct
import sys
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from services.flow.activity import AnalysisResult
from services.flow.models import ActivityCategory
from services.flow.observer import CapturedFrame, MockDesktopObserver, ObserverPipeline
from services.flow.observer.base import UnsupportedObserver, create_observer
from services.flow.observer.macos import (CaptureTimeout, HelperMissing, MacOSObserver, ObserverNotRunning,
                                          PermissionDenied)
from services.flow.observer.macos import active_window, cli_capture, permissions
from services.flow.observer.macos.helper import find_helper
from services.flow.observer.macos.imageinfo import image_size
from services.flow.observer.macos.runner import RunResult, run
from services.flow.observer.replay import ReplayScriptError, frames_from_script
from services.flow.privacy import PrivacyPolicy
from services.flow.session_manager import SessionManager
from services.flow.store import FlowStore

DARWIN = lambda: "Darwin"  # noqa: E731


def png(width=64, height=32) -> bytes:
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" * 3)) + chunk(b"IEND", b""))


def jpeg(width=80, height=48) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x01" * 9 + sof + b"\xff\xd9"


class FakeHelper:
    """Callable runner that speaks the helper's JSON protocol."""

    def __init__(self, app="Editor", bundle="com.x.editor", display=2, permission="granted", capture_error=None):
        self.app, self.bundle, self.display, self.permission = app, bundle, display, permission
        self.capture_error = capture_error
        self.calls: list[list[str]] = []

    def __call__(self, command, timeout):
        self.calls.append(list(command))
        verb = command[1]
        if verb == "version":
            return RunResult(0, b'{"ok":true,"version":"0.1.0"}\n')
        if verb == "permission":
            return RunResult(0, json.dumps({"ok": True, "screen_recording": self.permission}).encode() + b"\n")
        if verb == "context":
            return RunResult(0, json.dumps({"ok": True, "application": self.app, "bundle_id": self.bundle,
                                            "window_title": "secret title", "display_id": self.display,
                                            "pid": 1}).encode() + b"\n")
        if verb == "displays":
            return RunResult(0, json.dumps({"ok": True, "displays": [
                {"id": 1, "isMain": True, "scale": 2.0, "frame": {"x": 0, "y": 0, "width": 1512, "height": 982}},
                {"id": 2, "isMain": False, "scale": 1.0, "frame": {"x": 1512, "y": 0, "width": 1920, "height": 1080}},
            ]}).encode() + b"\n")
        if verb == "capture":
            if self.capture_error:
                return RunResult(3, json.dumps({"ok": False, "error": self.capture_error, "message": "nope"}).encode() + b"\n")
            data = jpeg(1280, 720)
            head = {"ok": True, "display_id": int(command[command.index("--display") + 1])
                    if command[command.index("--display") + 1].isdigit() else 1,
                    "width": 1280, "height": 720, "bytes": len(data), "latency_ms": 42}
            return RunResult(0, json.dumps(head).encode() + b"\n" + data)
        raise AssertionError(command)

    def captures(self):
        return [call for call in self.calls if call[1] == "capture"]


def observer_with(runner, **kwargs) -> MacOSObserver:
    kwargs.setdefault("helper_path", "/fake/flow-macos-observer")
    kwargs.setdefault("env", {"PATH": ""})
    return MacOSObserver(runner=runner, system=DARWIN, **kwargs)


@pytest.fixture
def fake_helper_path(monkeypatch, tmp_path):
    """find_helper() accepts the fake path as executable."""
    real = os.path.isfile
    monkeypatch.setattr("services.flow.observer.macos.helper._executable",
                        lambda path: str(path) == "/fake/flow-macos-observer" or (real(path) and os.access(path, os.X_OK)))


def run_async(coro):
    return asyncio.run(coro)


# -- helper protocol --------------------------------------------------------------------------
def test_helper_backend_captures_active_display_in_memory(fake_helper_path):
    runner = FakeHelper()
    observer = observer_with(runner)

    async def scenario():
        await observer.start()
        frame = await observer.snapshot()
        await observer.stop()
        return frame

    frame = run_async(scenario())
    assert observer.backend == "helper"
    assert frame.image_bytes and frame.image_bytes[:2] == b"\xff\xd8"
    assert (frame.width, frame.height, frame.application, frame.display_id) == (1280, 720, "Editor", "2")
    capture = runner.captures()[0]
    assert capture[capture.index("--display") + 1] == "2"  # display holding the frontmost window
    assert capture[-2:] == ["--out", "-"]  # pixels come back over the pipe, never a file


def test_context_reports_helper_metadata(fake_helper_path):
    observer = observer_with(FakeHelper(app="Safari", bundle="com.apple.Safari"))

    async def scenario():
        await observer.start()
        return await observer.active_context()

    context = run_async(scenario())
    assert (context.application, context.bundle_id, context.display_id) == ("Safari", "com.apple.Safari", "2")
    assert context.window_title == "secret title"


def test_displays_parse_helper_frame_and_scale(fake_helper_path):
    observer = observer_with(FakeHelper())

    async def scenario():
        await observer.start()
        return await observer.displays()

    displays = run_async(scenario())
    assert [d.id for d in displays] == ["1", "2"]
    assert displays[0].is_main and displays[0].scale == 2.0 and displays[1].width == 1920


def test_permission_denied_is_typed_and_not_started_is_typed(fake_helper_path):
    observer = observer_with(FakeHelper(capture_error="permission_denied"))

    async def scenario():
        with pytest.raises(ObserverNotRunning):
            await observer.snapshot()
        await observer.start()
        with pytest.raises(PermissionDenied) as info:
            await observer.snapshot()
        return info.value

    error = run_async(scenario())
    assert error.code == "permission_denied" and error.hint


def test_truncated_helper_frame_is_rejected(fake_helper_path):
    class Truncating(FakeHelper):
        def __call__(self, command, timeout):
            result = super().__call__(command, timeout)
            return RunResult(0, result.stdout[:-10]) if command[1] == "capture" else result

    observer = observer_with(Truncating())

    async def scenario():
        await observer.start()
        with pytest.raises(RuntimeError, match="truncated"):
            await observer.snapshot()

    run_async(scenario())


def test_macos13_helper_unsupported_falls_back_to_screencapture(fake_helper_path, monkeypatch):
    runner = FakeHelper(capture_error="unsupported_os")
    fallback_calls = []

    def fake_capture(image_format, max_dim, timeout, runner_arg):
        fallback_calls.append(image_format)
        return png(10, 5), 10, 5

    monkeypatch.setattr(cli_capture, "capture_main_display", fake_capture)
    observer = observer_with(runner)

    async def scenario():
        await observer.start()
        return await observer.snapshot()

    frame = run_async(scenario())
    assert observer.backend == "screencapture" and fallback_calls == ["jpeg"] and frame.width == 10


# -- real subprocess protocol (fake helper executable) -----------------------------------------
FAKE_SCRIPT = f"""#!{sys.executable}
import json, sys, time
verb = sys.argv[1]
if verb == "version":
    print(json.dumps({{"ok": True, "version": "fake"}}))
elif verb == "context":
    print(json.dumps({{"ok": True, "application": "Editor", "bundle_id": "b", "window_title": None, "display_id": 1}}))
elif verb == "permission":
    print(json.dumps({{"ok": True, "screen_recording": "granted"}}))
elif verb == "hang":
    time.sleep(30)
elif verb == "capture":
    if "--hang" in sys.argv:
        time.sleep(30)
    data = b"\\xff\\xd8" + b"x" * 100 + b"\\xff\\xd9"
    sys.stdout.write(json.dumps({{"ok": True, "display_id": 1, "width": 4, "height": 3, "bytes": len(data)}}) + "\\n")
    sys.stdout.flush()
    sys.stdout.buffer.write(data)
"""


def make_fake_helper(directory: Path) -> Path:
    path = directory / "flow-macos-observer"
    path.write_text(FAKE_SCRIPT)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_real_subprocess_helper_roundtrip_and_env_lookup(tmp_path):
    helper = make_fake_helper(tmp_path)
    assert find_helper(env={"FLOW_MACOS_HELPER": str(helper), "PATH": ""}) == str(helper)
    assert find_helper(env={"PATH": str(tmp_path)}) == str(helper)
    observer = MacOSObserver(system=DARWIN, env={"FLOW_MACOS_HELPER": str(helper), "PATH": ""})

    async def scenario():
        await observer.start()
        return await observer.snapshot()

    frame = run_async(scenario())
    assert observer.backend == "helper" and len(frame.image_bytes) == 104 and frame.application == "Editor"


def test_runner_enforces_timeout_and_reports_missing_binary(tmp_path):
    helper = make_fake_helper(tmp_path)
    with pytest.raises(CaptureTimeout) as info:
        run([str(helper), "hang"], 0.3)
    assert info.value.code == "timeout"
    with pytest.raises(HelperMissing):
        run([str(tmp_path / "does-not-exist"), "version"], 1)


def test_capture_timeout_surfaces_as_typed_error(tmp_path):
    helper = make_fake_helper(tmp_path)
    observer = MacOSObserver(system=DARWIN, env={"FLOW_MACOS_HELPER": str(helper), "PATH": ""},
                             capture_timeout=0.3)
    calls = []

    def hanging(command, timeout):
        calls.append(command[1])
        if command[1] == "capture":
            return run([command[0], "hang"], timeout)
        return run(command, timeout)

    observer.runner = hanging

    async def scenario():
        await observer.start()
        observer._helper.runner = hanging
        with pytest.raises(CaptureTimeout):
            await observer.snapshot()

    run_async(scenario())


# -- helper missing / CLI fallback --------------------------------------------------------------
def test_no_helper_and_no_fallback_raises_helper_missing(monkeypatch):
    monkeypatch.setattr("services.flow.observer.macos.screen_capture._screencapture_available", lambda: False)
    observer = MacOSObserver(system=DARWIN, env={"PATH": ""}, helper_path=None, runner=FakeHelper())
    monkeypatch.setattr("services.flow.observer.macos.screen_capture.find_helper", lambda *a, **k: None)

    async def scenario():
        with pytest.raises(HelperMissing) as info:
            await observer.start()
        return info.value

    assert run_async(scenario()).code == "helper_missing"


def test_non_macos_start_is_rejected():
    async def scenario():
        with pytest.raises(RuntimeError, match="macOS"):
            await MacOSObserver(system=lambda: "Linux").start()

    run_async(scenario())


def test_lsappinfo_parses_both_output_dialects():
    assert active_window.parse_lsappinfo('"LSDisplayName"="Safari"\n"CFBundleIdentifier"="com.apple.Safari"\n"pid"=42') \
        == ("Safari", "com.apple.Safari")
    assert active_window.parse_lsappinfo('name="Terminal"\nbundleID="com.apple.Terminal"') \
        == ("Terminal", "com.apple.Terminal")
    assert active_window.parse_lsappinfo("garbage") == (None, None)


class FakeCli:
    """Emulates lsappinfo, sips and screencapture, checking temp-file hygiene as it goes."""

    def __init__(self, app="Terminal", bundle="com.apple.Terminal", payload=None, fail=False):
        self.app, self.bundle, self.payload, self.fail = app, bundle, payload or jpeg(1600, 900), fail
        self.paths: list[str] = []
        self.dir_modes: list[int] = []
        self.file_modes: list[int] = []
        self.commands: list[list[str]] = []

    def __call__(self, command, timeout):
        self.commands.append(list(command))
        if command[0].endswith("lsappinfo"):
            if command[1] == "front":
                return RunResult(0, b"ASN:0x0-0x1c01c:\n")
            return RunResult(0, f'"LSDisplayName"="{self.app}"\n"CFBundleIdentifier"="{self.bundle}"\n'.encode())
        if command[0].endswith("screencapture"):
            path = command[-1]
            self.paths.append(path)
            self.dir_modes.append(stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode))
            self.file_modes.append(stat.S_IMODE(os.stat(path).st_mode))  # pre-created 0600 by FLOW
            if self.fail:
                return RunResult(1, b"", b"could not create image from display 1")
            with open(path, "wb") as handle:
                handle.write(self.payload)
            return RunResult(0)
        if command[0].endswith("sips"):
            return RunResult(0)
        raise AssertionError(command)


def cli_observer(runner, monkeypatch, privacy=None, permission="granted"):
    monkeypatch.setattr("services.flow.observer.macos.screen_capture.find_helper", lambda *a, **k: None)
    monkeypatch.setattr("services.flow.observer.macos.screen_capture._screencapture_available", lambda: True)
    monkeypatch.setattr(permissions, "_coregraphics", lambda symbol: permission == "granted")
    return MacOSObserver(runner=runner, system=DARWIN, privacy=privacy, env={"PATH": ""})


def test_cli_fallback_uses_private_temp_file_and_unlinks_immediately(monkeypatch):
    runner = FakeCli()
    observer = cli_observer(runner, monkeypatch)

    async def scenario():
        await observer.start()
        return await observer.snapshot()

    frame = run_async(scenario())
    assert observer.backend == "screencapture"
    assert frame.image_bytes == runner.payload and (frame.width, frame.height) == (1600, 900)
    assert frame.application == "Terminal" and frame.window_title is None  # CLI cannot see window titles
    assert runner.dir_modes == [0o700] and runner.file_modes == [0o600]
    path = runner.paths[0]
    assert not os.path.exists(path) and not os.path.exists(os.path.dirname(path))
    capture = next(c for c in runner.commands if c[0].endswith("screencapture"))
    assert capture[:5] == ["/usr/sbin/screencapture", "-x", "-t", "jpg", "-D"]


def test_cli_fallback_cleans_up_even_when_capture_fails(monkeypatch):
    runner = FakeCli(fail=True)
    observer = cli_observer(runner, monkeypatch)

    async def scenario():
        await observer.start()
        with pytest.raises(RuntimeError, match="screencapture failed"):
            await observer.snapshot()

    run_async(scenario())
    assert runner.paths and not os.path.exists(runner.paths[0]) and not os.path.exists(os.path.dirname(runner.paths[0]))


def test_cli_fallback_denied_permission_is_typed(monkeypatch):
    runner = FakeCli()
    observer = cli_observer(runner, monkeypatch, permission="denied")

    async def scenario():
        await observer.start()
        with pytest.raises(PermissionDenied):
            await observer.snapshot()

    run_async(scenario())
    assert not any(c[0].endswith("screencapture") for c in runner.commands)


def test_image_size_probe_reads_png_and_jpeg_headers():
    assert image_size(png(640, 480)) == (640, 480)
    assert image_size(jpeg(1280, 720)) == (1280, 720)
    assert image_size(b"not an image") is None


# -- permissions ---------------------------------------------------------------------------------
def test_permission_status_from_helper_and_platform_gate(fake_helper_path):
    assert permissions.screen_recording_status("/fake/flow-macos-observer", FakeHelper(permission="granted"),
                                               DARWIN).screen_recording == "granted"
    denied = permissions.screen_recording_status("/fake/flow-macos-observer", FakeHelper(permission="denied"), DARWIN)
    assert (denied.screen_recording, denied.source) == ("denied", "helper")
    assert permissions.screen_recording_status(system=lambda: "Linux").screen_recording == "unavailable"


def test_permission_status_falls_back_to_coregraphics_then_unknown(monkeypatch):
    monkeypatch.setattr(permissions, "find_helper", lambda *a, **k: None)
    monkeypatch.setattr(permissions, "_coregraphics", lambda symbol: True)
    assert permissions.screen_recording_status(system=DARWIN).source == "coregraphics"
    monkeypatch.setattr(permissions, "_coregraphics", lambda symbol: None)
    assert permissions.screen_recording_status(system=DARWIN).screen_recording == "unknown"


# -- privacy: excluded apps never reach the capture layer -----------------------------------------
def test_excluded_app_skips_capture_before_any_pixels_helper(fake_helper_path):
    runner = FakeHelper(app="1Password", bundle="com.1password")
    observer = observer_with(runner, privacy=PrivacyPolicy({"1password"}))

    async def scenario():
        await observer.start()
        context = await observer.active_context()
        return context, await observer.snapshot()

    context, frame = run_async(scenario())
    assert frame is None and runner.captures() == []
    assert context.window_title is None  # excluded window titles are never surfaced


def test_excluded_app_skips_capture_before_any_pixels_cli(monkeypatch):
    runner = FakeCli(app="Messages", bundle="com.apple.MobileSMS")
    observer = cli_observer(runner, monkeypatch, privacy=PrivacyPolicy({"messages"}))

    async def scenario():
        await observer.start()
        return await observer.snapshot()

    assert run_async(scenario()) is None
    assert not any(c[0].endswith("screencapture") for c in runner.commands) and runner.paths == []


def test_excluded_bundle_id_is_also_honoured(fake_helper_path):
    runner = FakeHelper(app="Some App", bundle="com.bank.app")
    observer = observer_with(runner, privacy=PrivacyPolicy({"com.bank.app"}))

    async def scenario():
        await observer.start()
        return await observer.snapshot()

    assert run_async(scenario()) is None and runner.captures() == []


class SpyObserver(MockDesktopObserver):
    def __init__(self, frames):
        super().__init__(frames)
        self.snapshots = 0

    async def snapshot(self, reason=None):
        self.snapshots += 1
        return await super().snapshot()


class Analyzer:
    calls = 0

    async def analyze(self, goal, frame, context, history):
        Analyzer.calls += 1
        return AnalysisResult("Editing", ActivityCategory.CORE_TASK, .9, .5, .9)


def test_pipeline_never_snapshots_excluded_app_and_stores_no_title():
    async def scenario():
        with tempfile.TemporaryDirectory() as path:
            manager = SessionManager(FlowStore(path))
            session = manager.start_session("goal")
            frame = CapturedFrame(datetime.now(timezone.utc), application="1Password",
                                  window_title="Vault: bank PIN", image_bytes=b"secret")
            observer = SpyObserver([frame])
            await observer.start()
            Analyzer.calls = 0
            item = await ObserverPipeline(session.id, "goal", observer, Analyzer(), manager).observe_once()
            stored = manager.observations(session.id)
            return observer, item, stored, frame

    observer, item, stored, frame = run_async(scenario())
    assert observer.snapshots == 0 and Analyzer.calls == 0
    assert item.metadata["excluded"] is True and item.window_title is None
    assert all(o.window_title is None for o in stored)
    assert frame.image_bytes == b"secret"  # never touched, never analysed


def test_pipeline_discards_frame_if_focus_moved_to_excluded_app_mid_capture():
    class Racy(MockDesktopObserver):
        async def active_context(self):  # context looked fine ...
            from services.flow.observer import ObserverContext
            return ObserverContext("Editor")

    async def scenario():
        with tempfile.TemporaryDirectory() as path:
            manager = SessionManager(FlowStore(path))
            session = manager.start_session("goal")
            frame = CapturedFrame(datetime.now(timezone.utc), application="Messages", window_title="mom",
                                  image_bytes=b"pixels")  # ... but the captured frame is an excluded app
            observer = Racy([frame])
            await observer.start()
            Analyzer.calls = 0
            item = await ObserverPipeline(session.id, "goal", observer, Analyzer(), manager,
                                          PrivacyPolicy({"messages"})).observe_once()
            return item, frame

    item, frame = run_async(scenario())
    assert Analyzer.calls == 0 and frame.image_bytes is None
    assert item.metadata["excluded"] is True and item.window_title is None


def test_privacy_resumes_after_excluded_app():
    async def scenario():
        with tempfile.TemporaryDirectory() as path:
            manager = SessionManager(FlowStore(path))
            session = manager.start_session("goal")
            now = datetime.now(timezone.utc)
            frames = [CapturedFrame(now, application="Messages", image_bytes=b"a"),
                      CapturedFrame(now, application="Editor", image_bytes=b"b")]
            observer = MockDesktopObserver(frames)
            await observer.start()
            pipeline = ObserverPipeline(session.id, "goal", observer, Analyzer(), manager, PrivacyPolicy({"messages"}))
            first = await pipeline.observe_once()
            observer._index = 1  # focus moved on; the excluded frame was never consumed
            second = await pipeline.observe_once()
            return first, second

    first, second = run_async(scenario())
    assert first.metadata["excluded"] is True and second.category == ActivityCategory.CORE_TASK


def test_unchanged_frame_pixels_are_discarded():
    async def scenario():
        with tempfile.TemporaryDirectory() as path:
            manager = SessionManager(FlowStore(path))
            session = manager.start_session("goal")
            now = datetime.now(timezone.utc)
            frames = [CapturedFrame(now, application="Editor", image_bytes=b"same"),
                      CapturedFrame(now, application="Editor", image_bytes=b"same")]
            observer = MockDesktopObserver(frames)
            await observer.start()
            pipeline = ObserverPipeline(session.id, "goal", observer, Analyzer(), manager)
            await pipeline.observe_once()
            await pipeline.observe_once()
            return frames[1]

    assert run_async(scenario()).image_bytes is None


# -- create_observer / replay ----------------------------------------------------------------------
def test_create_observer_replay_from_json_script(monkeypatch, tmp_path):
    script = tmp_path / "replay.json"
    script.write_text(json.dumps({"frames": [
        {"application": "Editor", "window_title": "auth.py", "text": "one", "offset_seconds": 0},
        {"application": "Social", "offset_seconds": 60, "reason": "drift_probe"}]}))
    monkeypatch.setenv("FLOW_OBSERVER", "replay")
    monkeypatch.setenv("FLOW_OBSERVER_SCRIPT", str(script))
    observer = create_observer()
    assert isinstance(observer, MockDesktopObserver)

    async def scenario():
        await observer.start()
        context = await observer.active_context()
        return context, await observer.snapshot(), await observer.snapshot(), await observer.snapshot()

    context, first, second, third = run_async(scenario())
    assert context.application == "Editor" and first.image_bytes == b"one"
    assert second.reason.value == "drift_probe" and third is None


def test_create_observer_replay_default_script_and_bad_script(monkeypatch, tmp_path):
    monkeypatch.setenv("FLOW_OBSERVER", "replay")
    monkeypatch.delenv("FLOW_OBSERVER_SCRIPT", raising=False)
    assert len(create_observer().frames) == 6
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setenv("FLOW_OBSERVER_SCRIPT", str(bad))
    with pytest.raises(ReplayScriptError):
        create_observer()
    with pytest.raises(ReplayScriptError):
        frames_from_script({"frames": [{"application": "x", "image_base64": "@@@"}]})


def test_create_observer_platform_selection(monkeypatch):
    monkeypatch.delenv("FLOW_OBSERVER", raising=False)
    monkeypatch.setattr("services.flow.observer.base.platform.system", lambda: "Linux")
    assert isinstance(create_observer(), UnsupportedObserver)
    monkeypatch.setattr("services.flow.observer.base.platform.system", lambda: "Darwin")
    assert isinstance(create_observer(PrivacyPolicy({"x"})), MacOSObserver)
    monkeypatch.setenv("FLOW_OBSERVER", "bogus")
    with pytest.raises(ValueError):
        create_observer()
