import time

import pytest
from starlette.websockets import WebSocketDisconnect

from cloud_helpers import event, observation


def ws_device(client, device, hello=True):
    ws = client.websocket_connect("/v1/ws/device", headers=device.headers)
    conn = ws.__enter__()
    assert conn.receive_json()["type"] == "ready"
    if hello:
        conn.send_json({"type": "hello", "device_id": device.device_id, "flow_version": "0.2.0", "active_sessions": [],
                        "health": {"observer": "healthy", "vision": "ready"}})
    return ws, conn


def presence(client, alice, device):
    items = client.get("/v1/devices", headers=alice.web).json()["items"]
    return next(i for i in items if i["id"] == device.device_id)["presence"]["state"]


def wait_for(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def cmd(client, actor, **body):
    return client.post("/v1/commands", headers=actor.web if hasattr(actor, "web") else actor.headers, json=body)


def test_presence_online_degraded_offline(client, alice):
    device = alice.authorize_device()
    assert presence(client, alice, device) == "offline"
    ws, conn = ws_device(client, device)
    assert wait_for(lambda: presence(client, alice, device) == "online")
    conn.send_json({"type": "heartbeat", "health": {"observer": "error", "vision": "ready"}, "active_sessions": []})
    assert wait_for(lambda: presence(client, alice, device) == "degraded")
    ws.__exit__(None, None, None)
    assert wait_for(lambda: presence(client, alice, device) == "offline")


def test_stale_heartbeat_reads_as_offline(client, alice, app):
    device = alice.authorize_device()
    ws, conn = ws_device(client, device)
    assert wait_for(lambda: presence(client, alice, device) == "online")
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from services.flowcloud import db
    with app.state.cloud.repo.engine.begin() as c:
        c.execute(update(db.device_presence).values(last_heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=120)))
    assert presence(client, alice, device) == "offline"
    ws.__exit__(None, None, None)


def test_web_start_command_delivered_acked_and_session_appears(client, alice):
    device = alice.authorize_device()
    refused = cmd(client, alice, type="START", device_id=device.device_id, payload={"goal": "Fix auth tests"})
    assert refused.status_code == 409 and refused.json()["error"] == "device_offline"
    ws, conn = ws_device(client, device)
    assert wait_for(lambda: presence(client, alice, device) == "online")
    created = cmd(client, alice, type="START", device_id=device.device_id, payload={"goal": "Fix auth tests"})
    assert created.status_code == 201, created.text
    body = created.json()
    session_id = body["payload"]["session_id"]
    assert body["source"] == "web" and body["status"] == "queued"
    frame = conn.receive_json()
    assert frame["type"] == "command" and frame["command"]["command_id"] == body["command_id"]
    assert frame["command"]["status"] == "delivered" and frame["command"]["payload"]["goal"] == "Fix auth tests"
    got = client.get(f"/v1/commands/{body['command_id']}", headers=alice.web).json()
    assert got["status"] == "delivered", "socket delivery is not success"
    conn.send_json({"type": "ack", "command_id": body["command_id"], "status": "running"})
    assert wait_for(lambda: client.get(f"/v1/commands/{body['command_id']}", headers=alice.web).json()["status"] == "running")
    assert device.create_session(goal="Fix auth tests", session_id=session_id) == session_id
    conn.send_json({"type": "ack", "command_id": body["command_id"], "status": "succeeded", "result": {"session_id": session_id}})
    assert wait_for(lambda: client.get(f"/v1/commands/{body['command_id']}", headers=alice.web).json()["status"] == "succeeded")
    conn.send_json({"type": "ack", "command_id": body["command_id"], "status": "failed"})
    time.sleep(0.2)
    assert client.get(f"/v1/commands/{body['command_id']}", headers=alice.web).json()["status"] == "succeeded", "terminal is final"
    assert client.get(f"/v1/sessions/{session_id}", headers=alice.web).status_code == 200
    ws.__exit__(None, None, None)


def test_commands_are_idempotent_by_command_id(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    first = cmd(client, alice, type="STOP", session_id=sid, command_id="cmd_idem_00001", payload={})
    again = cmd(client, alice, type="STOP", session_id=sid, command_id="cmd_idem_00001", payload={})
    assert first.status_code == 201 and again.status_code == 200
    assert first.json() == again.json()
    rows = client.get(f"/v1/sessions/{sid}/commands", headers=alice.web).json()["items"]
    assert len(rows) == 1


def test_offline_queue_only_for_safe_commands_and_delivery_on_reconnect(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    assert cmd(client, alice, type="ADD_TASK", session_id=sid, payload={"instruction": "run tests"}).status_code == 409
    assert cmd(client, alice, type="EXECUTE_RECOMMENDATION", session_id=sid, payload={"recommendation_id": "rec_1"}).status_code == 409
    stop = cmd(client, alice, type="STOP", session_id=sid, payload={})
    pause = cmd(client, alice, type="PAUSE", session_id=sid, payload={})
    mute = cmd(client, alice, type="MUTE_VOICE", session_id=sid, payload={"minutes": 15})
    assert {r.status_code for r in (stop, pause, mute)} == {201}
    assert stop.json()["status"] == "queued"
    ws, conn = ws_device(client, device)
    types = [conn.receive_json()["command"]["type"] for _ in range(3)]
    assert types == ["STOP", "PAUSE", "MUTE_VOICE"], "delivered oldest first"
    ws.__exit__(None, None, None)
    ws2, conn2 = ws_device(client, device)
    redelivered = [conn2.receive_json()["command"]["command_id"] for _ in range(3)]
    assert redelivered == [stop.json()["command_id"], pause.json()["command_id"], mute.json()["command_id"]], "at-least-once until acked"
    ws2.__exit__(None, None, None)


def test_expired_commands_are_never_delivered(client, alice, app):
    device = alice.authorize_device(); sid = device.create_session()
    made = cmd(client, alice, type="STOP", session_id=sid, payload={}).json()
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from services.flowcloud import db
    with app.state.cloud.repo.engine.begin() as c:
        c.execute(update(db.commands).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    ws, conn = ws_device(client, device)
    time.sleep(0.3)
    assert client.get(f"/v1/commands/{made['command_id']}", headers=alice.web).json()["status"] == "expired"
    conn.send_json({"type": "heartbeat", "health": {}, "active_sessions": []})
    ws.__exit__(None, None, None)


def test_ack_authorization(client, alice, bob):
    a = alice.authorize_device(); other = alice.authorize_device(device_id="dev_otheralice00001")
    sid = a.create_session()
    made = cmd(client, alice, type="PAUSE", session_id=sid, payload={}).json()
    url = f"/v1/commands/{made['command_id']}/ack"
    assert client.post(url, headers=alice.web, json={"status": "succeeded"}).status_code == 403
    assert client.post(url, headers=other.headers, json={"status": "succeeded"}).status_code == 404
    assert client.post(url, headers=a.headers, json={"status": "queued"}).status_code == 422
    ok = client.post(url, headers=a.headers, json={"status": "succeeded", "result": {"paused": True}})
    assert ok.status_code == 200 and ok.json()["status"] == "succeeded"


def test_payload_validation(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    ws, conn = ws_device(client, device)
    assert wait_for(lambda: presence(client, alice, device) == "online")
    bad = [dict(type="ADD_TASK", session_id=sid, payload={}), dict(type="ADD_TASK", session_id=sid, payload={"instruction": "x", "permission_level": "destructive"}),
           dict(type="APPROVE_ACTION", session_id=sid, payload={"approval_id": "../../etc"}), dict(type="MUTE_VOICE", session_id=sid, payload={"minutes": 99999}),
           dict(type="SET_PERMISSION_POLICY", session_id=sid, payload={"policy": "yolo"}), dict(type="START", payload={"goal": "g"}),
           dict(type="FOO", session_id=sid, payload={}), dict(type="ASK", payload={"question": "?"})]
    for body in bad:
        assert cmd(client, alice, **body).status_code == 422, body
    ok = cmd(client, alice, type="ADD_TASK", session_id=sid, payload={"instruction": "Inspect auth dependency versions"})
    assert ok.status_code == 201
    ws.__exit__(None, None, None)


def test_cli_device_token_can_command_its_own_user_sessions(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    r = client.post("/v1/commands", headers=device.headers, json={"type": "PAUSE", "session_id": sid, "payload": {}, "source": "cli"})
    assert r.status_code == 201 and r.json()["source"] == "cli"


def test_command_on_completed_session(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    client.post(f"/v1/sessions/{sid}/stop", headers=device.headers, json={})
    stop = cmd(client, alice, type="STOP", session_id=sid, payload={})
    assert stop.status_code == 201 and stop.json()["status"] == "succeeded"
    assert cmd(client, alice, type="PAUSE", session_id=sid, payload={}).status_code == 409


# ---- viewer websockets ---------------------------------------------------------------------------
def viewer(client, path, token, **frame):
    ws = client.websocket_connect(path)
    conn = ws.__enter__()
    conn.send_json({"type": "auth", "token": token, **frame})
    return ws, conn


def test_session_stream_replays_after_last_sequence_then_streams_live(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    url = f"/v1/sessions/{sid}/events"
    for n in range(1, 4):
        client.post(url, headers=device.headers, json=event(n, "observation.created", n=n))
    ws, conn = viewer(client, f"/v1/ws/sessions/{sid}", alice.web["Authorization"][7:], last_sequence=1)
    assert conn.receive_json()["type"] == "ready"
    replayed = [conn.receive_json()["event"]["sequence"] for _ in range(2)]
    assert replayed == [2, 3]
    assert conn.receive_json()["type"] == "presence"
    client.post(url, headers=device.headers, json=event(4, "metrics.updated", drift_state="focused"))
    live = conn.receive_json()
    assert live["type"] == "event" and live["event"]["sequence"] == 4 and live["event"]["data"]["drift_state"] == "focused"
    client.post(url, headers=device.headers, json=event(3, "observation.created", n=3))  # duplicate: nothing pushed
    late = {**event(9, "drift.changed", to="drifting"), "id": "evt_gapfill_9"}
    client.post(url, headers=device.headers, json=late)
    assert conn.receive_json()["event"]["sequence"] == 9
    ws.__exit__(None, None, None)


def test_session_stream_delivers_command_status_changes(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    ws, conn = viewer(client, f"/v1/ws/sessions/{sid}", alice.web["Authorization"][7:])
    conn.receive_json(); conn.receive_json()
    made = cmd(client, alice, type="PAUSE", session_id=sid, payload={}).json()
    frame = conn.receive_json()
    assert frame["type"] == "command" and frame["command"]["command_id"] == made["command_id"]
    client.post(f"/v1/commands/{made['command_id']}/ack", headers=device.headers, json={"status": "succeeded"})
    assert conn.receive_json()["command"]["status"] == "succeeded"
    ws.__exit__(None, None, None)


def test_user_stream_carries_presence_and_approvals(client, alice):
    device = alice.authorize_device(); sid = device.create_session()
    ws, conn = viewer(client, "/v1/ws/user", alice.web["Authorization"][7:])
    assert conn.receive_json()["type"] == "ready"
    dws, dconn = ws_device(client, device)
    seen = set()
    for _ in range(3):
        seen.add(conn.receive_json()["type"])
        if "presence" in seen:
            break
    assert "presence" in seen
    approval = {"id": "appr_00000001", "session_id": sid, "task_id": "task_00000001", "action": {"tool": "run_tests"},
                "risk": "low", "status": "pending", "requested_at": "2026-09-19T10:00:00Z", "revision": 1}
    client.post(f"/v1/sessions/{sid}/entities:batch", headers=device.headers, json={"items": [
        {"kind": "approval", "id": "appr_00000001", "revision": 1, "data": approval}]})
    types = []
    for _ in range(4):
        frame = conn.receive_json(); types.append(frame["type"])
        if frame["type"] == "approval":
            assert frame["approval"]["id"] == "appr_00000001"
            break
    assert "approval" in types
    listed = client.get("/v1/approvals?status=pending", headers=alice.web).json()["items"]
    assert listed[0]["id"] == "appr_00000001" and listed[0]["session_id"] == sid
    dws.__exit__(None, None, None); ws.__exit__(None, None, None)
