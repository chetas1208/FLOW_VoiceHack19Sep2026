import importlib.util,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(path,name):
 spec=importlib.util.spec_from_file_location(name,ROOT/path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
G=load('services/graph/graph.py','g');D=load('services/discovery/discover.py','d');S=load('services/runtime/scenarios.py','s');Q=load('services/runtime/queue.py','q')
class Wave6(unittest.TestCase):
 def test_graph_provenance(self):
  with tempfile.TemporaryDirectory() as t:
   g=G.Graph(Path(t)/'g.db');g.node('a','file','v1',{},'source');g.node('b','symbol','v1',{},'source');g.edge('a','b','DEFINES','v1','ast');self.assertEqual(g.neighbors('a')[0][0],'b')
   with self.assertRaises(ValueError):g.edge('a','missing','DEFINES','v1','ast')
 def test_discovery(self):
  with tempfile.TemporaryDirectory() as t:
   g=G.Graph(Path(t)/'g.db');self.assertGreater(D.discover(ROOT/'reference_apps',g),0)
 def test_agentic_ground_truth(self):
  with tempfile.TemporaryDirectory() as t:
   r=S.run_scenario({'kind':'agentic'},t);self.assertEqual(r['verdict'],'FAIL');self.assertFalse(r['assertions']['project-exists'])
 def test_fullstack_retry(self):
  with tempfile.TemporaryDirectory() as t:
   r=S.run_scenario({'kind':'fullstack'},t);self.assertEqual(r['verdict'],'FAIL')
 def test_fault_injection(self):
  with tempfile.TemporaryDirectory() as t:
   r=S.run_scenario({'kind':'fault-injection'},t);self.assertEqual(r['verdict'],'FAIL')
 def test_queue_ownership(self):
  with tempfile.TemporaryDirectory() as t:
   q=Q.Queue(Path(t)/'q.db');id=q.submit({'kind':'agentic'});self.assertEqual(q.claim('a')[0],id);self.assertIsNone(q.claim('b'))
   with self.assertRaises(PermissionError):q.complete(id,'b',{})
   q.complete(id,'a',{'ok':True});self.assertIsNone(q.claim('a'))
 def test_graph_execution_link(self):
  with tempfile.TemporaryDirectory() as t:
   g=G.Graph(Path(t)/'g.db');r=S.run_scenario({'kind':'agentic'},Path(t)/'runs',g);self.assertEqual(g.neighbors('scenario:agentic')[0][0],'run:'+r['run_id'])
if __name__=='__main__':unittest.main()
