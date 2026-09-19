from fastapi.testclient import TestClient


def test_v1_report_recommendation_and_ask_are_local_and_grounded(tmp_path, monkeypatch):
    from services.flow.api import router
    from services.flow.session_manager import SessionManager
    from services.flow.store import FlowStore
    from fastapi import FastAPI

    app = FastAPI()
    app.state.flow_manager = SessionManager(FlowStore(tmp_path))
    app.include_router(router)
    client = TestClient(app)
    created = client.post("/v1/sessions", json={"goal": "Fix authentication tests"})
    assert created.status_code == 201
    session_id = created.json()["id"]
    report = client.get(f"/v1/sessions/{session_id}/report")
    assert report.status_code == 200 and report.json()["observation_count"] == 0
    recommendation = client.get(f"/v1/sessions/{session_id}/recommendation")
    assert recommendation.status_code == 200
    answer = client.post(f"/v1/sessions/{session_id}/ask", json={"question": "What am I working on?"})
    assert answer.status_code == 200 and answer.json()["intent"] == "doing"
