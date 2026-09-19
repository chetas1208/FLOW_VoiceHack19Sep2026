import asyncio
import tempfile
from pathlib import Path

from services.flow.activity import validate_analysis
from services.flow.auth import CLIAuthRequest
from services.flow.credentials import FileCredentialStore, MemoryCredentialStore
from services.flow.daemon import FlowDaemon, request
from services.flow.observer import AdaptiveSampler, CapturedFrame, MockDesktopObserver, SamplerConfig
from services.flow.privacy import PrivacyPolicy, redact_text
from services.flow.cloud.uploader import QueueUploader
from services.flow.queue import OfflineQueue


def test_packaged_auth_and_credentials_do_not_expose_tokens():
    auth = CLIAuthRequest.create("dev_test")
    assert "code_verifier" not in auth.authorization_url("https://app.flow.ai")
    assert auth.challenge != auth.verifier
    with tempfile.TemporaryDirectory() as directory:
        store = FileCredentialStore(Path(directory) / "credentials.json")
        store.save_token("secret-token", "refresh-token")
        assert store.get_token() == "secret-token"
        assert oct((Path(directory) / "credentials.json").stat().st_mode & 0o777) == "0o600"


def test_observer_sampler_privacy_and_analysis_validation():
    sampler = AdaptiveSampler(SamplerConfig(base_interval=10, burst_interval=2, focus_interval=20, max_interval=30))
    assert sampler.next_interval(context_changed=True) == 2
    assert sampler.next_interval(focused=True) == 20
    assert "[EMAIL_REDACTED]" in redact_text("contact a@example.com")
    policy = PrivacyPolicy(); policy.add_exclusion("Bank App"); assert policy.is_excluded("bank app")
    result = validate_analysis({"activity_summary": "editing tests", "category": "core_task",
                                "goal_alignment": .9, "progress_signal": .5, "confidence": .8})
    assert result.category.value == "core_task"


def test_mock_observer_and_bounded_offline_credentials():
    async def run():
        observer = MockDesktopObserver([CapturedFrame(__import__("datetime").datetime.now(__import__("datetime").timezone.utc), application="Editor")])
        await observer.start(); frame = await observer.snapshot(); await observer.stop()
        assert frame.application == "Editor" and observer.started is False
    asyncio.run(run())
    store = MemoryCredentialStore(); store.save_token("x"); assert store.get_token() == "x"; store.delete_token(); assert store.get_token() is None


def test_daemon_ipc_round_trip():
    async def run():
        with tempfile.TemporaryDirectory() as directory:
            daemon = FlowDaemon(Path(directory) / "flow.sock")
            task = asyncio.create_task(daemon.run())
            for _ in range(50):
                if daemon.socket.exists(): break
                await asyncio.sleep(.01)
            assert (await request("ping", daemon.socket))["status"] == "ok"
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
    asyncio.run(run())


def test_offline_uploader_keeps_failed_items_and_acks_successes():
    async def run():
        with tempfile.TemporaryDirectory() as directory:
            queue = OfflineQueue(Path(directory) / "queue.sqlite3")
            queue.put({"id": "one"}); queue.put({"id": "two"})
            calls = {"two": 0}
            async def send(payload):
                if payload["id"] == "two":
                    calls["two"] += 1
                    raise RuntimeError("offline")
            assert await QueueUploader(queue, send, max_attempts=2, base_delay=0).flush() == 1
            assert len(queue) == 1 and calls["two"] == 2
    asyncio.run(run())
