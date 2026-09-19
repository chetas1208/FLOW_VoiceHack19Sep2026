import os,tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from services.platform.regression import select,FULL

class PlatformTests(unittest.TestCase):
 def test_impact(self):
  self.assertEqual(select(['reference_apps/agentic/agent.py']),('agentic',))
  self.assertEqual(select(['reference_apps/fullstack/app.py']),('fullstack','fault-injection'))
  self.assertEqual(select(['unrecognized/file']),FULL)
  self.assertEqual(select(['contracts/schemas/verdict.schema.json']),FULL)
 def test_api_reference_run(self):
  with tempfile.TemporaryDirectory() as tmp:
   os.environ['QA_DATA_DIR']=tmp
   import importlib
   from services.platform import api
   importlib.reload(api)
   client=TestClient(api.app)
   self.assertEqual(client.get('/health').status_code,200)
   self.assertEqual(client.post('/jobs',json={'kind':'unknown'}).status_code,422)
   r=client.post('/jobs',json={'kind':'agentic'});self.assertEqual(r.status_code,202)
   job=r.json()['job_id'];done=client.post('/workers/run-once');self.assertEqual(done.status_code,200)
   self.assertEqual(client.get('/jobs/'+job).json()['status'],'completed')
   self.assertEqual(client.get('/jobs/'+job).json()['result']['verdict'],'FAIL')
   self.assertTrue(client.get('/runs').json())
