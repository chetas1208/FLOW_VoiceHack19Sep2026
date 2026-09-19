"""OTLP/HTTP gzip content encoding, as sent by the Collector's otlphttp exporter."""
import gzip
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from services.telemetry.receiver import app

HEADERS = {'content-type': 'application/x-protobuf'}


def _request(name='gz.span'):
    req = ExportTraceServiceRequest()
    span = req.resource_spans.add().scope_spans.add().spans.add()
    span.trace_id, span.span_id, span.name = b'\x0a' * 16, b'\x0b' * 8, name
    return req.SerializeToString()


def test_gzip_export_is_indexed_and_identity_still_works():
    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'QA_DATA_DIR': temp}):
        client = TestClient(app)
        assert client.post('/v1/traces', content=gzip.compress(_request()),
                           headers={**HEADERS, 'content-encoding': 'gzip'}).status_code == 200
        assert client.post('/v1/traces', content=_request('plain.span'), headers=HEADERS).status_code == 200
        with sqlite3.connect(Path(temp) / 'telemetry.sqlite3') as db:
            names = {row[0] for row in db.execute('SELECT name FROM spans')}
        assert names == {'gz.span'}  # same trace/span ID: INSERT OR IGNORE keeps the first


def test_hostile_encodings_are_refused():
    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'QA_DATA_DIR': temp}):
        client = TestClient(app)
        bomb = gzip.compress(b'\0' * (3 * 1024 * 1024))  # ~3 KiB that inflates to 3 MiB
        assert len(bomb) < 64 * 1024
        assert client.post('/v1/traces', content=bomb, headers={**HEADERS, 'content-encoding': 'gzip'}).status_code == 413
        assert client.post('/v1/traces', content=b'not gzip', headers={**HEADERS, 'content-encoding': 'gzip'}).status_code == 400
        assert client.post('/v1/traces', content=gzip.compress(_request())[:-6],
                           headers={**HEADERS, 'content-encoding': 'gzip'}).status_code == 400
        assert client.post('/v1/traces', content=_request(), headers={**HEADERS, 'content-encoding': 'br'}).status_code == 415
