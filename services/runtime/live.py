"""OTLP-instrumented real HTTP + Python agent reference tests.

Exporter delivery is separately verified by an OTLP receiver integration test.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from services.runtime.wave1 import configure_telemetry, now
from services.fullstack_qa.live import verify_retry
from services.agentic_qa.adapter import verify_project_creation


def execute(kind, output, endpoint=None):
    if kind not in ('agentic','fullstack'):
        raise ValueError('Unsupported adapter')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    provider,tracer=configure_telemetry(endpoint)
    run_id=str(uuid4())
    try:
        with tracer.start_as_current_span('qa.execute_live',attributes={'qa.run.id':run_id,'qa.kind':kind}) as span:
            trace_id=f'{span.get_span_context().trace_id:032x}'
            with tracer.start_as_current_span('qa.application_execution'):
                result=verify_retry() if kind=='fullstack' else verify_project_creation()
            with tracer.start_as_current_span('qa.independent_verification',attributes={'qa.verdict':result['verdict']}):
                pass
        blob=json.dumps(result['observed'],sort_keys=True).encode()
        digest=hashlib.sha256(blob).hexdigest()
        (output/f'{digest}.json').write_bytes(blob)
        record={'run_id':run_id,'kind':kind,'verdict':result['verdict'],'assertions':result['assertions'],'trace_id':trace_id,'evidence_sha256':digest,'created_at':now(),'otlp_export_configured':bool(endpoint)}
        (output/f'{run_id}.json').write_text(json.dumps(record,indent=2)+'\n')
        with sqlite3.connect(output/'live.sqlite3') as db:
            db.execute('CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY,kind TEXT,verdict TEXT,trace_id TEXT,evidence_sha256 TEXT)')
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?)',(run_id,kind,result['verdict'],trace_id,digest))
        return record
    finally:
        # A configured exporter is not proof of successful delivery.
        provider.force_flush(timeout_millis=5000)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('kind',choices=['agentic','fullstack']);p.add_argument('--output',default='.local-runs');p.add_argument('--otlp-endpoint',default=os.getenv('QA_OTLP_TRACES_ENDPOINT'))
    a=p.parse_args();print(json.dumps(execute(a.kind,a.output,a.otlp_endpoint),indent=2))
