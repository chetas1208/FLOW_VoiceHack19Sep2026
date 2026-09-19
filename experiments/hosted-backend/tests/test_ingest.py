import json

from cloud_helpers import event, observation


def obs_url(sid, suffix=""):
    return f"/v1/sessions/{sid}/observations{suffix}"


def test_session_create_is_idempotent_and_cross_device_safe(client, alice):
    device = alice.authorize_device()
    sid = device.create_session()
    again = client.post("/v1/sessions", headers=device.headers, json={"id": sid, "goal": "x", "started_at": "2026-09-19T10:00:00Z"})
    assert again.status_code == 200 and again.json()["goal"] == "Finish authentication"
    other = alice.authorize_device(device_id="dev_seconddevice123")
    clash = client.post("/v1/sessions", headers=other.headers, json={"id": sid, "goal": "x", "started_at": "2026-09-19T10:00:00Z"})
    assert clash.status_code == 409


def test_observation_ingest_is_idempotent(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    first = client.post(obs_url(sid), headers=device.headers, json=observation(1))
    assert first.status_code == 201 and first.json()["status"] == "created"
    dup = client.post(obs_url(sid), headers=device.headers, json=observation(1))
    assert dup.status_code == 200 and dup.json()["status"] == "duplicate"
    rows = client.get(obs_url(sid), headers=alice.web).json()["items"]
    assert len(rows) == 1 and rows[0]["application"] == "VS Code"


def test_sequence_gaps_are_reported_not_fatal(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    for n in (41, 42, 44):
        r = client.post(obs_url(sid), headers=device.headers, json=observation(n))
        assert r.status_code == 201
    sync = r.json()["sync"]["observations"]
    assert sync["highest_sequence"] == 44 and sync["received"] == 3 and 43 in sync["missing"]
    fill = client.post(obs_url(sid), headers=device.headers, json=observation(43))
    assert fill.status_code == 201 and 43 not in fill.json()["sync"]["observations"]["missing"]


def test_sequence_conflict_with_different_id(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    client.post(obs_url(sid), headers=device.headers, json=observation(1))
    r = client.post(obs_url(sid), headers=device.headers, json=observation(1, id="obs_different1"))
    assert r.status_code == 409


def test_batch_ingest_dedupes_and_reports_per_item(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    client.post(obs_url(sid), headers=device.headers, json=observation(2))
    batch = [observation(n) for n in range(1, 6)] + []
    r = client.post(obs_url(sid, ":batch"), headers=device.headers, json={"observations": batch})
    assert r.status_code == 200
    statuses = {x["sequence"]: x["status"] for x in r.json()["results"]}
    assert statuses == {1: "created", 2: "duplicate", 3: "created", 4: "created", 5: "created"}
    assert r.json()["sync"]["observations"]["missing"] == []
    assert len(client.get(obs_url(sid), headers=alice.web).json()["items"]) == 5


def test_batch_limits_and_atomic_validation(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    too_many = {"observations": [observation(n) for n in range(1, 102)]}
    assert client.post(obs_url(sid, ":batch"), headers=device.headers, json=too_many).status_code == 422
    bad = {"observations": [observation(1), observation(2, goal_alignment=7)]}
    assert client.post(obs_url(sid, ":batch"), headers=device.headers, json=bad).status_code == 422
    assert client.get(obs_url(sid), headers=alice.web).json()["items"] == []
    dup = {"observations": [observation(1), observation(1, id="obs_other_id1")]}
    assert client.post(obs_url(sid, ":batch"), headers=device.headers, json=dup).status_code == 422


def test_validation_rejects_bad_payloads(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    for bad in ({"goal_alignment": 1.2}, {"confidence": -0.1}, {"category": "productive"}, {"timestamp": "1999-01-01T00:00:00Z"},
                {"sequence": 0}, {"activity": "x" * 1001}, {"image": "aGVsbG8="}, {"screenshot": "abc"}, {"window_title": "secret"}):
        body = observation(1); body.update(bad)
        assert client.post(obs_url(sid), headers=device.headers, json=body).status_code == 422, bad


def test_events_ingest_idempotent_and_status_effects(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    url = f"/v1/sessions/{sid}/events"
    assert client.post(url, headers=device.headers, json=event(1, "session.started", goal="g")).status_code == 201
    assert client.post(url, headers=device.headers, json=event(1, "session.started", goal="g")).json()["status"] == "duplicate"
    client.post(url, headers=device.headers, json=event(2, "session.paused", status="paused"))
    assert client.get(f"/v1/sessions/{sid}", headers=alice.web).json()["session"]["status"] == "paused"
    client.post(url, headers=device.headers, json=event(3, "session.resumed", status="active"))
    assert client.get(f"/v1/sessions/{sid}", headers=alice.web).json()["session"]["status"] == "active"
    client.post(url, headers=device.headers, json=event(4, "session.completed", status="completed"))
    detail = client.get(f"/v1/sessions/{sid}", headers=alice.web).json()["session"]
    assert detail["status"] == "completed" and detail["ended_at"]
    late = client.post(url, headers=device.headers, json={**event(3, "session.resumed"), "id": "evt_late_0003"})
    assert late.status_code == 409, "same sequence with another id is a conflict"
    got = client.get(f"/v1/sessions/{sid}/events?after=2", headers=alice.web).json()["items"]
    assert [e["sequence"] for e in got] == [3, 4]


def test_out_of_order_status_events_do_not_regress_state(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    url = f"/v1/sessions/{sid}/events:batch"
    r = client.post(url, headers=device.headers, json={"events": [event(5, "session.completed"), event(4, "session.paused")]})
    assert r.status_code == 200
    assert client.get(f"/v1/sessions/{sid}", headers=alice.web).json()["session"]["status"] == "completed"


def test_forbidden_event_types_and_raw_pixels_rejected(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    url = f"/v1/sessions/{sid}/events"
    assert client.post(url, headers=device.headers, json=event(1, "shell.exec")).status_code == 422
    assert client.post(url, headers=device.headers, json=event(1, "observation.created", nested={"image": "AAAA"})).status_code == 422
    assert client.post(url, headers=device.headers, json=event(1, "observation.created", blob="x" * 20000)).status_code == 422


def test_body_size_limits_and_content_type(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    huge = json.dumps(observation(1, activity="a" * 200000))
    r = client.post(obs_url(sid), headers={**device.headers, "Content-Type": "application/json"}, content=huge)
    assert r.status_code == 413
    r = client.post(obs_url(sid), headers={**device.headers, "Content-Type": "image/png"}, content=b"\x89PNG....")
    assert r.status_code == 415
    chunked = client.post(obs_url(sid), headers={**device.headers, "Content-Type": "application/json"},
                          content=(chunk for chunk in [b"{" + b"x" * 40000, b"y" * 40000]))
    assert chunked.status_code == 413


def test_web_token_cannot_ingest(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    assert client.post(obs_url(sid), headers=alice.web, json=observation(1)).status_code == 403


def test_another_device_of_same_user_cannot_write_session(client, alice):
    a = alice.authorize_device(); b = alice.authorize_device(device_id="dev_otherdevice5678")
    sid = a.create_session()
    assert client.post(obs_url(sid), headers=b.headers, json=observation(1)).status_code == 403
    assert client.get(obs_url(sid), headers=b.headers).status_code == 200


def test_segments_upsert_by_revision_and_interventions(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    seg = {"id": "seg_00000001", "start": "2026-09-19T10:00:00Z", "end": "2026-09-19T10:05:00Z", "activity": "Debugging",
           "category": "core_task", "application": "VS Code", "alignment": .9, "confidence": .8, "observation_count": 5, "revision": 1}
    assert client.post(f"/v1/sessions/{sid}/segments", headers=device.headers, json=seg).json()["status"] == "created"
    assert client.post(f"/v1/sessions/{sid}/segments", headers=device.headers, json=seg).json()["status"] == "duplicate"
    seg2 = {**seg, "end": "2026-09-19T10:09:00Z", "revision": 2, "observation_count": 9}
    assert client.post(f"/v1/sessions/{sid}/segments", headers=device.headers, json=seg2).json()["status"] == "updated"
    stale = client.post(f"/v1/sessions/{sid}/segments", headers=device.headers, json=seg).json()["status"]
    assert stale == "stale"
    detail = client.get(f"/v1/sessions/{sid}", headers=alice.web).json()
    assert len(detail["segments"]) == 1 and detail["segments"][0]["observation_count"] == 9
    inter = {"id": "int_00000001", "timestamp": "2026-09-19T10:06:00Z", "reason": "sustained_goal_drift", "channel": "voice",
             "message": "hello", "status": "delivered", "metadata": {}}
    assert client.post(f"/v1/sessions/{sid}/interventions", headers=device.headers, json=inter).status_code == 201
    assert client.post(f"/v1/sessions/{sid}/interventions", headers=device.headers, json=inter).status_code == 200
    assert len(client.get(f"/v1/sessions/{sid}", headers=alice.web).json()["interventions"]) == 1


def test_summary_versions_and_stop_report(client, alice, app):
    device = alice.authorize_device(); sid = device.create_session()
    for n in range(1, 4):
        client.post(obs_url(sid), headers=device.headers, json=observation(n, timestamp=f"2026-09-19T10:0{n}:00Z"))
    summary = {"goal": "Finish authentication", "duration_seconds": 600, "active_seconds": 540, "away_seconds": 60,
               "goal_alignment": .9, "focus_continuity": .8, "context_stability": .95, "progress": .6, "session_score": 82.5,
               "coverage": 1.0, "confidence": .9, "segments": [], "blockers": [], "drift_periods": [], "interventions": [],
               "recommendations": ["Run the full suite"]}
    assert client.put(f"/v1/sessions/{sid}/summary", headers=device.headers, json=summary).status_code == 201
    assert client.put(f"/v1/sessions/{sid}/summary", headers=device.headers, json=summary).status_code == 200
    stop = client.post(f"/v1/sessions/{sid}/stop", headers=device.headers, json={})
    assert stop.status_code == 200 and stop.json()["status"] == "completed"
    assert client.post(f"/v1/sessions/{sid}/stop", headers=device.headers, json={}).status_code == 200
    report = client.get(f"/v1/sessions/{sid}/report", headers=alice.web).json()
    assert report["source"] == "device" and report["summary"]["session_score"] == 82.5
    assert {"human", "agent", "recommendations", "approvals", "voice_interventions"} <= report.keys()
    late = client.post(obs_url(sid), headers=device.headers, json=observation(4))
    assert late.status_code == 201, "offline catch-up after stop must still be accepted"


def test_worker_derives_summary_when_device_sent_none(client, alice, app):
    device = alice.authorize_device(); sid = device.create_session()
    for n in range(1, 5):
        client.post(obs_url(sid), headers=device.headers, json=observation(n, timestamp=f"2026-09-19T10:0{n}:00Z"))
    client.post(f"/v1/sessions/{sid}/stop", headers=device.headers, json={})
    from datetime import timedelta
    from services.flowcloud import worker
    from services.flowcloud.repo import now
    from sqlalchemy import update
    from services.flowcloud import db
    with app.state.cloud.repo.engine.begin() as conn:
        conn.execute(update(db.jobs).values(run_after=now() - timedelta(seconds=1)))
    assert worker.run_one(app.state.cloud) is True
    report = client.get(f"/v1/sessions/{sid}/report", headers=alice.web).json()
    assert report["source"] == "cloud" and report["summary"]["extra"]["observations"] == 4


def test_history_pagination_and_filters(client, alice):
    a = alice.authorize_device(name="Mac A"); b = alice.authorize_device(name="Mac B", device_id="dev_macbdevice12345")
    ids = []
    for i in range(5):
        dev = a if i % 2 == 0 else b
        sid = "ses_%016d" % i
        client.post("/v1/sessions", headers=dev.headers, json={"id": sid, "goal": f"g{i}", "started_at": f"2026-09-1{i}T10:00:00Z"})
        ids.append(sid)
    page1 = client.get("/v1/sessions?limit=2", headers=alice.web).json()
    assert [s["id"] for s in page1["items"]] == [ids[4], ids[3]] and page1["next_cursor"]
    page2 = client.get(f"/v1/sessions?limit=2&cursor={page1['next_cursor']}", headers=alice.web).json()
    assert [s["id"] for s in page2["items"]] == [ids[2], ids[1]]
    only_b = client.get(f"/v1/sessions?device_id={b.device_id}", headers=alice.web).json()["items"]
    assert {s["id"] for s in only_b} == {ids[1], ids[3]} and only_b[0]["device_name"] == "Mac B"
    since = client.get("/v1/sessions?since=2026-09-13T00:00:00Z", headers=alice.web).json()["items"]
    assert {s["id"] for s in since} == {ids[3], ids[4]}
    client.post(f"/v1/sessions/{ids[0]}/stop", headers=a.headers, json={})
    done = client.get("/v1/sessions?status=completed", headers=alice.web).json()["items"]
    assert [s["id"] for s in done] == [ids[0]]


def test_entities_ingest_versioning_and_live_view(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    task = {"id": "task_00000001", "session_id": sid, "user_id": "u", "device_id": device.device_id, "instruction": "Run tests",
            "status": "running", "created_from": "web", "created_at": "2026-09-19T10:00:00Z", "permission_level": "safe_execute",
            "plan": [], "evidence": [], "revision": 2}
    r = client.post(f"/v1/sessions/{sid}/entities:batch", headers=device.headers, json={"items": [
        {"kind": "task", "id": "task_00000001", "revision": 2, "data": task},
        {"kind": "runtime_state", "id": "current", "revision": 1, "data": {"status": "executing_delegated_task", "voice": "ready", "observer": "healthy"}}]})
    assert r.status_code == 200, r.text
    assert [x["status"] for x in r.json()["results"]] == ["created", "created"]
    stale = client.post(f"/v1/sessions/{sid}/entities:batch", headers=device.headers, json={"items": [
        {"kind": "task", "id": "task_00000001", "revision": 1, "data": {**task, "status": "queued", "revision": 1}}]})
    assert stale.json()["results"][0]["status"] == "stale"
    live = client.get(f"/v1/sessions/{sid}/live", headers=alice.web).json()
    assert live["agent"]["status"] == "running" and live["session"]["status"] == "executing_delegated_task"
    assert live["presence"]["state"] == "offline"
    bad = client.post(f"/v1/sessions/{sid}/entities:batch", headers=device.headers, json={"items": [
        {"kind": "task", "id": "task_00000002", "revision": 1, "data": {**task, "id": "task_other0001"}}]})
    assert bad.status_code == 422
    assert client.post(f"/v1/sessions/{sid}/entities:batch", headers=device.headers, json={"items": [
        {"kind": "shell", "id": "x1", "revision": 1, "data": {}}]}).status_code == 422
