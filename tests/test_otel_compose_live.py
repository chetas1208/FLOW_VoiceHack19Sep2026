"""Live Collector -> receiver -> SQLite path from infra/otel/compose.yaml.

Opt-in (QA_OTEL_COMPOSE_LIVE=1) with the stack already up; see infra/otel/README.md.
"""
import os
import sqlite3
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.getenv('QA_OTEL_COMPOSE_LIVE') != '1', reason='opt-in live Collector deployment test')
DB = Path(__file__).resolve().parents[1] / '.local-runs' / 'telemetry.sqlite3'


def test_span_sent_to_collector_is_indexed_by_receiver():
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    provider = TracerProvider(resource=Resource.create({'service.name': 'compose-live-test'}))
    provider.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(
        endpoint=os.getenv('QA_COLLECTOR_TRACES', 'http://127.0.0.1:4318/v1/traces'))))
    run_id = str(uuid.uuid4())
    for _ in range(40):  # the Collector may still be starting
        with provider.get_tracer('live').start_as_current_span('collector.live', attributes={'qa.run.id': run_id}) as span:
            trace_id = f'{span.get_span_context().trace_id:032x}'
        provider.force_flush()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if DB.exists():
                with sqlite3.connect(DB) as db:
                    row = db.execute('SELECT name, service, run_id FROM spans WHERE trace_id=?', (trace_id,)).fetchone()
                if row:
                    provider.shutdown()
                    assert row == ('collector.live', 'compose-live-test', run_id)
                    return
            time.sleep(0.2)
    provider.shutdown()
    pytest.fail('span never reached telemetry.sqlite3 through the Collector')
