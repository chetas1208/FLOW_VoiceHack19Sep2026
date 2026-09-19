import os
import tempfile
from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from services.telemetry.receiver import app, read_trace


def test_otlp_receiver_persists_safe_attributes_and_requires_token():
    with tempfile.TemporaryDirectory() as temp:
        old={x:os.environ.get(x) for x in ('QA_DATA_DIR','QA_OTLP_INGEST_TOKEN')}
        os.environ['QA_DATA_DIR']=temp
        os.environ['QA_OTLP_INGEST_TOKEN']='test-ingestion-key'
        try:
            client=TestClient(app)
            req=ExportTraceServiceRequest()
            resource=req.resource_spans.add()
            attr=resource.resource.attributes.add()
            attr.key='service.name';attr.value.string_value='reference-agent'
            span=resource.scope_spans.add().spans.add()
            span.trace_id=bytes.fromhex('ab'*16)
            span.span_id=bytes.fromhex('01'*8)
            span.name='qa.run'
            attr=span.attributes.add();attr.key='qa.run.id';attr.value.string_value='run-a'
            sensitive=span.attributes.add();sensitive.key='gen_ai.prompt';sensitive.value.string_value='super secret'
            blob=req.SerializeToString()
            assert client.post('/v1/traces',content=blob,headers={'Content-Type':'application/x-protobuf'}).status_code==401
            headers={'Content-Type':'application/x-protobuf','x-qa-otlp-token':'test-ingestion-key'}
            result=client.post('/v1/traces',content=blob,headers=headers)
            assert result.status_code==200,result.text
            assert client.post('/v1/traces',content=blob,headers=headers).status_code==200
            rows=read_trace('ab'*16)
            assert len(rows)==1
            assert rows[0]['service']=='reference-agent'
            assert rows[0]['run_id']=='run-a'
            assert 'gen_ai.prompt' not in rows[0]['attributes']
            assert client.post('/v1/traces',content=b'not protobuf',headers=headers).status_code==400
        finally:
            for k,v in old.items():
                if v is None:os.environ.pop(k,None)
                else:os.environ[k]=v
