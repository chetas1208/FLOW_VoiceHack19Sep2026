"""Minimal OTLP/HTTP protobuf trace receiver with persistent, sanitized indexing.

This is an OTLP receiver, not a full OpenTelemetry Collector replacement.
Supports traces only: no logs/metrics, tail sampling, distributed HA or mTLS.
Bind to loopback and place behind a trusted Collector/proxy for real deployments.
"""
import hmac
import zlib
import os
import re
import sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest, ExportTraceServiceResponse)
from google.protobuf.message import DecodeError

app=FastAPI(title='ProofHound OTLP development receiver')
DB=Path(os.getenv('QA_DATA_DIR','.local-runs')).resolve()/'telemetry.sqlite3'
SAFE_ATTRIBUTES={
    'service.name','qa.run.id','qa.project.id','qa.scenario.id','qa.kind',
    'qa.step.name','qa.step.target','qa.verdict','qa.step.infra_error',
    'http.request.method','http.response.status_code',
    'gen_ai.operation.name','gen_ai.agent.name','gen_ai.tool.name',
}


def database():
    db=Path(os.getenv('QA_DATA_DIR','.local-runs')).resolve()/'telemetry.sqlite3'
    db.parent.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(db,timeout=10)
    connection.executescript('''
        CREATE TABLE IF NOT EXISTS spans(
          trace_id TEXT NOT NULL, span_id TEXT NOT NULL, parent_id TEXT,
          name TEXT NOT NULL, service TEXT NOT NULL, run_id TEXT,
          start_ns INTEGER, end_ns INTEGER, attributes TEXT NOT NULL,
          PRIMARY KEY(trace_id,span_id));
        CREATE INDEX IF NOT EXISTS spans_run ON spans(run_id);
    ''')
    return connection


MAX_BODY=2_097_152


def decode_body(body,encoding):
    """OTLP/HTTP allows gzip (the Collector's otlphttp exporter default).

    Decompression is streamed and capped so a small compressed body cannot expand
    past MAX_BODY (decompression bomb). Other encodings are refused."""
    encoding=(encoding or 'identity').strip().lower()
    if encoding in ('','identity'):
        return body
    if encoding!='gzip':
        raise HTTPException(415,'unsupported OTLP content encoding')
    inflater=zlib.decompressobj(16+zlib.MAX_WBITS)
    try:
        data=inflater.decompress(body,MAX_BODY+1)
    except zlib.error as exc:
        raise HTTPException(400,'invalid gzip OTLP body') from exc
    if len(data)>MAX_BODY or inflater.unconsumed_tail:
        raise HTTPException(413,'decompressed OTLP request exceeds 2MiB')
    if not inflater.eof:
        raise HTTPException(400,'truncated gzip OTLP body')
    return data


def safe_attributes(attrs):
    values={}
    for attribute in attrs:
        key=attribute.key
        if key not in SAFE_ATTRIBUTES:
            continue
        value=attribute.value
        which=value.WhichOneof('value')
        if which not in ('string_value','int_value','bool_value'):
            continue
        v=getattr(value,which)
        if isinstance(v,str):
            v=v[:128]
        values[key]=v
    return values


@app.post('/v1/traces')
async def ingest(request:Request):
    if request.client and request.client.host not in ('127.0.0.1','::1','testclient') and os.getenv('QA_ALLOW_PUBLIC_OTLP')!='1':
        raise HTTPException(403,'loopback-only development receiver')
    secret=os.getenv('QA_OTLP_INGEST_TOKEN')
    if secret and not hmac.compare_digest(request.headers.get('x-qa-otlp-token',''),secret):
        raise HTTPException(401,'OTLP ingestion authentication required')
    if 'application/x-protobuf' not in request.headers.get('content-type',''):
        raise HTTPException(415,'OTLP protobuf content type required')
    if int(request.headers.get('content-length','0') or 0)>MAX_BODY:
        raise HTTPException(413,'OTLP request exceeds 2MiB')
    body=await request.body()
    if len(body)>MAX_BODY:
        raise HTTPException(413,'OTLP request exceeds 2MiB')
    body=decode_body(body,request.headers.get('content-encoding'))
    proto=ExportTraceServiceRequest()
    try:
        proto.ParseFromString(body)
    except DecodeError as exc:
        raise HTTPException(400,'invalid OTLP protobuf') from exc
    import json
    rows=[]
    for resource in proto.resource_spans:
        resource_attrs=safe_attributes(resource.resource.attributes)
        service=resource_attrs.get('service.name','unknown')
        for scope in resource.scope_spans:
            for span in scope.spans:
                attrs=safe_attributes(span.attributes)
                if len(span.trace_id)!=16 or len(span.span_id)!=8:
                    raise HTTPException(400,'invalid trace/span identifier length')
                rows.append((span.trace_id.hex(),span.span_id.hex(),span.parent_span_id.hex(),
                             span.name[:128],service,attrs.get('qa.run.id'),
                             span.start_time_unix_nano,span.end_time_unix_nano,
                             json.dumps(attrs,sort_keys=True)))
                if len(rows)>1000:
                    raise HTTPException(413,'more than 1000 spans in one request')
    with database() as db:
        db.executemany('INSERT OR IGNORE INTO spans VALUES (?,?,?,?,?,?,?,?,?)',rows)
    return Response(content=ExportTraceServiceResponse().SerializeToString(),
                    media_type='application/x-protobuf')


def read_trace(trace_id):
    if not re.fullmatch('[a-f0-9]{32}',trace_id):
        raise ValueError('invalid trace ID')
    import json
    with database() as db:
        rows=db.execute('SELECT trace_id,span_id,parent_id,name,service,run_id,start_ns,end_ns,attributes '
                        'FROM spans WHERE trace_id=? ORDER BY start_ns',(trace_id,)).fetchall()
    keys=('trace_id','span_id','parent_id','name','service','run_id','start_ns','end_ns','attributes')
    return [{**dict(zip(keys,row)),'attributes':json.loads(row[-1])} for row in rows]
