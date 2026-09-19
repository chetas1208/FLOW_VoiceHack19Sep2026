"""Narrow A2A JSON-RPC 0.3.0 adapter: benchmark skill only.

Supports message/send and tasks/get plus an Agent Card. Not a claim of
full A2A conformance (no streaming, push, auth negotiation, or cancellation).
API middleware is responsible for authentication.
"""
import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from benchmarks.benchmark import benchmark

router = APIRouter()


def storage():
    path = Path(os.getenv('QA_DATA_DIR', '.local-runs')).resolve() / 'a2a.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, task TEXT NOT NULL)')
    return path


def make_error(id, code, message):
    return {'jsonrpc': '2.0', 'id': id, 'error': {'code': code, 'message': message}}


@router.get('/.well-known/agent-card.json')
def card():
    base = os.getenv('QA_PUBLIC_URL', 'http://127.0.0.1:8080').rstrip('/')
    return {
        'protocolVersion': '0.3.0', 'name': 'ProofHound Benchmark',
        'description': 'Limited read-only A2A adapter for running the local reference benchmark.',
        'url': base+'/a2a', 'preferredTransport': 'JSONRPC',
        'version': '0.5.0', 'capabilities': {'streaming': False, 'pushNotifications': False},
        'defaultInputModes': ['text/plain'], 'defaultOutputModes': ['text/plain'],
        'skills': [{'id': 'qa-benchmark', 'name': 'Run QA reference benchmark',
                    'description': 'Execute known-good and known-bad synthetic reference applications.',
                    'tags': ['qa', 'benchmark'], 'examples': ['run qa benchmark']}],
        **({'securitySchemes': {'apiKey': {'type': 'apiKey', 'in': 'header', 'name': 'x-qa-api-token'}},
            'security': [{'apiKey': []}]} if os.getenv('QA_API_TOKEN') else {}),
    }


@router.post('/a2a')
async def rpc(request: Request):
    try:
        payload = await request.json()
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(make_error(None, -32700, 'Parse error'))
    if not isinstance(payload, dict) or payload.get('jsonrpc') != '2.0' or 'id' not in payload or not isinstance(payload.get('method'), str):
        return JSONResponse(make_error(payload.get('id') if isinstance(payload, dict) else None, -32600, 'Invalid request'))
    id, method, params = payload['id'], payload['method'], payload.get('params', {})
    if not isinstance(params, dict):
        return JSONResponse(make_error(id, -32602, 'Invalid params'))
    if method == 'tasks/get':
        task_id = params.get('id')
        if not isinstance(task_id, str):
            return JSONResponse(make_error(id, -32602, 'Task ID required'))
        with sqlite3.connect(storage()) as db:
            row = db.execute('SELECT task FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            return JSONResponse(make_error(id, -32001, 'Task not found'))
        return JSONResponse({'jsonrpc': '2.0', 'id': id, 'result': json.loads(row[0])})
    if method != 'message/send':
        return JSONResponse(make_error(id, -32601, 'Method not implemented'))
    message = params.get('message')
    if not isinstance(message, dict) or message.get('role') != 'user' or not isinstance(message.get('parts'), list):
        return JSONResponse(make_error(id, -32602, 'User message with parts required'))
    if len(message['parts']) != 1 or message['parts'][0] != {'kind':'text','text':'run qa benchmark'}:
        return JSONResponse(make_error(id, -32602, 'Only the exact benchmark skill is supported'))
    task_id, context_id = str(uuid4()), str(uuid4())
    # No untrusted code or arbitrary URL is accepted through the A2A adapter.
    try:
        report = benchmark(Path(os.getenv('QA_DATA_DIR', '.local-runs')).resolve())
        good = report['known_defect_detection'] == report['known_defect_total'] and report['false_failure_count'] == 0
        status = 'completed' if good else 'failed'
        detail = (f"{report['known_defect_detection']}/{report['known_defect_total']} known defects detected; "
                  f"{report['false_failure_count']}/{report['known_good_total']} false failures; "
                  'four reference cases only')
    except Exception:
        status = 'failed'
        detail = 'Local benchmark execution failed'
    task = {'kind':'task', 'id':task_id, 'contextId':context_id,
            'status':{'state':status},
            'artifacts':[{'artifactId':str(uuid4()), 'name':'qa-benchmark-summary',
                          'parts':[{'kind':'text','text':detail}]}]}
    with sqlite3.connect(storage()) as db:
        db.execute('INSERT INTO tasks VALUES (?,?)', (task_id, json.dumps(task)))
    return JSONResponse({'jsonrpc':'2.0', 'id':id, 'result':task})
