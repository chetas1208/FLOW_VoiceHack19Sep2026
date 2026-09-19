import tempfile
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from services.flow.models import ActivityCategory, Observation, SessionStatus, utc_now
from services.flow.session_manager import InvalidTransition, SessionManager, SessionNotFound
from services.flow.store import FlowStore


def make_manager(path):
    return SessionManager(FlowStore(path))


def observation(session_id, timestamp, alignment, category=ActivityCategory.CORE_TASK, progress=None):
    return Observation("obs_" + str(timestamp.timestamp()), session_id, timestamp, "test", "editor",
                       category=category, goal_alignment=alignment, progress_signal=progress, confidence=.9)


def test_lifecycle_and_persistence():
    with tempfile.TemporaryDirectory() as path:
        manager = make_manager(path)
        session = manager.start_session("Ship authentication")
        assert manager.pause_session(session.id).status == SessionStatus.PAUSED
        assert manager.resume_session(session.id).status == SessionStatus.ACTIVE
        completed = manager.stop_session(session.id)
        assert completed.ended_at is not None
        assert make_manager(path).get_session(session.id).status == SessionStatus.COMPLETED
        assert make_manager(path).stop_session(session.id).status == SessionStatus.COMPLETED
        with pytest.raises(InvalidTransition): make_manager(path).resume_session(session.id)


def test_unknown_session_and_observation_validation():
    with tempfile.TemporaryDirectory() as path:
        manager = make_manager(path)
        with pytest.raises(SessionNotFound): manager.get_session("ses_missing")
        session = manager.start_session("test")
        with pytest.raises(ValueError): manager.add_observation(session.id, observation(session.id, utc_now(), 1.1))
        with pytest.raises(ValueError): manager.add_observation(session.id, Observation("obs-x", "ses-other", utc_now(), "test"))


def test_metrics_are_time_weighted_and_drift_needs_sustained_low_alignment():
    with tempfile.TemporaryDirectory() as path:
        manager = make_manager(path)
        session = manager.start_session("test")
        start = utc_now()
        manager.add_observation(session.id, observation(session.id, start, .9, progress=.8))
        manager.add_observation(session.id, observation(session.id, start + timedelta(seconds=10), .1, ActivityCategory.DISTRACTION))
        manager.add_observation(session.id, observation(session.id, start + timedelta(seconds=20), .1, ActivityCategory.DISTRACTION))
        assert manager.metrics(session.id).drift_state.value == "sustained_drift"
        assert manager.metrics(session.id).goal_alignment == pytest.approx(.5)
        assert manager.events(session.id)[-1].sequence > manager.events(session.id)[0].sequence
        assert len(manager.interventions(session.id)) == 1


def test_api_lifecycle_observation_and_replay():
    with tempfile.TemporaryDirectory() as path:
        from services.platform import api
        api.app.state.flow_manager = make_manager(path)
        client = TestClient(api.app)
        created = client.post("/flow/sessions", json={"goal": "Pass tests"})
        assert created.status_code == 201, created.text
        session_id = created.json()["id"]
        assert client.post(f"/flow/sessions/{session_id}/observations", json={
            "source": "simulator", "category": "core_task", "goal_alignment": .9,
        }).status_code == 201
        assert client.get(f"/flow/sessions/{session_id}").json()["observation_count"] == 1
        assert [item["sequence"] for item in client.get(f"/flow/sessions/{session_id}/events").json()] == [1, 2, 3]
        with client.websocket_connect(f"/ws/flow/sessions/{session_id}?after=2") as socket:
            assert socket.receive_json()["type"] == "metrics.updated"
        assert client.post("/flow/sessions/ses_missing/stop").status_code == 404
        assert client.post(f"/flow/sessions/{session_id}/observations", json={"source": "x", "goal_alignment": 2}).status_code == 422
        assert client.post(f"/flow/sessions/{session_id}/stop").status_code == 200
        assert client.post(f"/flow/sessions/{session_id}/pause").status_code == 409
