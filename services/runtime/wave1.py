"""Trusted, local reference-fixture runner. NOT a sandbox for untrusted projects."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from reference_apps.agentic.agent import FakeProjectTool, ProjectAgent
from reference_apps.fullstack.app import ORDERS, create_order


def now():
    return datetime.now(timezone.utc).isoformat()


_TELEMETRY = None

def configure_telemetry(endpoint=None):
    """Real OTLP/HTTP exporter. Endpoint is opt-in; never pretend an export succeeded."""
    global _TELEMETRY
    if _TELEMETRY is not None:
        if endpoint != _TELEMETRY[2]:
            raise RuntimeError("Telemetry endpoint cannot change within one process")
        return _TELEMETRY[:2]
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    provider = TracerProvider(resource=Resource.create({"service.name": "proofhound-reference-runner"}))
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=endpoint, headers={'x-qa-otlp-token': os.environ['QA_OTLP_INGEST_TOKEN']}
            if os.getenv('QA_OTLP_INGEST_TOKEN') else None)))
    trace.set_tracer_provider(provider)
    _TELEMETRY = (provider, trace.get_tracer("proofhound.wave1"), endpoint)
    return _TELEMETRY[:2]


def execute(kind, output, endpoint=None):
    if kind not in ("agentic", "fullstack"):
        raise ValueError("Unsupported reference fixture")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid4())
    provider, tracer = configure_telemetry(endpoint)
    started = now()
    run = {"schema_version":"1.0","run_id":run_id,"scenario_id":f"known-defect-{kind}","version_id":"reference-v1","environment_id":"trusted-local-fixture","status":"running","started_at":started,"trace_ids":[],"evidence_ids":[]}
    try:
        with tracer.start_as_current_span("qa.execute_scenario", attributes={"qa.run.id":run_id,"qa.scenario.id":run["scenario_id"],"qa.fixture.kind":kind}) as span:
            trace_id = format(span.get_span_context().trace_id,"032x")
            run["trace_ids"].append(trace_id)
            if kind == "agentic":
                tool = FakeProjectTool()
                with tracer.start_as_current_span("agent.invoke"):
                    reply = ProjectAgent(tool).run("demo")
                observed = {"reply":reply,"projects":tool.projects,"tool_calls":tool.calls}
                passed = "demo" in tool.projects
                assertion = "project-exists"
            else:
                ORDERS.clear()
                with tracer.start_as_current_span("http.order.create"):
                    create_order("order-1",50)
                    create_order("order-1",50)
                observed = {"order":ORDERS["order-1"],"charge_count":len(ORDERS["order-1"]["charges"])}
                passed = observed["charge_count"] == 1
                assertion = "exactly-one-charge"
            with tracer.start_as_current_span("qa.verify_state",attributes={"qa.assertion.id":assertion,"qa.assertion.passed":passed}):
                pass
        payload = json.dumps(observed,sort_keys=True,indent=2).encode()
        digest = hashlib.sha256(payload).hexdigest()
        evidence_id = str(uuid4())
        (output/f"{digest}.json").write_bytes(payload)
        evidence = {"schema_version":"1.0","evidence_id":evidence_id,"run_id":run_id,"kind":"state_snapshot","uri":f"sha256:{digest}","sha256":digest,"collected_at":now(),"redacted":True}
        run.update(status="completed",finished_at=now(),evidence_ids=[evidence_id])
        verdict = {"schema_version":"1.0","verdict_id":str(uuid4()),"run_id":run_id,"status":"PASS" if passed else "FAIL","assertion_results":[{"assertion_id":assertion,"status":"PASS" if passed else "FAIL","evidence_ids":[evidence_id]}],"evidence_ids":[evidence_id],"reason":"Independent fixture state assertion","evaluator_version":"wave1-v1"}
        trace_ref = {"schema_version":"1.0","run_id":run_id,"trace_id":trace_id,"service_name":"proofhound-reference-runner"}
        with sqlite3.connect(output/"runs.sqlite3") as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, verdict TEXT NOT NULL, trace_id TEXT NOT NULL, evidence_sha256 TEXT NOT NULL, created_at TEXT NOT NULL)")
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?)",(run_id,kind,run["status"],verdict["status"],trace_id,digest,now()))
        for name,data in (("run",run),("verdict",verdict),("evidence",evidence),("trace-reference",trace_ref)):
            (output/f"{run_id}.{name}.json").write_text(json.dumps(data,indent=2)+"\n")
        return {"run":run,"verdict":verdict,"evidence":evidence,"trace_reference":trace_ref}
    finally:
        provider.force_flush(timeout_millis=5000)
        # Keep the process-wide provider alive for subsequent local test runs.


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("kind",choices=["agentic","fullstack"])
    parser.add_argument("--output",default=".local-runs")
    parser.add_argument("--otlp-endpoint",default=os.getenv("QA_OTLP_TRACES_ENDPOINT"))
    args=parser.parse_args()
    result=execute(args.kind,args.output,args.otlp_endpoint)
    print(json.dumps({"run_id":result["run"]["run_id"],"verdict":result["verdict"]["status"],"trace_id":result["trace_reference"]["trace_id"],"otlp_export_configured":bool(args.otlp_endpoint)},indent=2))
