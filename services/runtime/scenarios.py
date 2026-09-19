"""Controlled fixture scenarios; no arbitrary command execution or production credentials."""
import importlib.util, json, hashlib, sqlite3, sys
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from reference_apps.agentic.agent import FakeProjectTool,ProjectAgent
from reference_apps.fullstack.app import ORDERS,create_order
from datetime import datetime,timezone
def utc():return datetime.now(timezone.utc).isoformat()
def run_scenario(scenario,output,graph=None):
 kind=scenario['kind']; name=scenario.get('name','demo'); output=Path(output);output.mkdir(parents=True,exist_ok=True)
 if kind=='agentic':
  tool=FakeProjectTool(); response=ProjectAgent(tool).run(name)
  observed={'response':response,'projects':tool.projects,'tool_calls':tool.calls}
  assertions={'project-exists':name in tool.projects,'tool-called':name in tool.calls}
 elif kind=='fullstack':
  ORDERS.clear();create_order('order-1',50)
  if scenario.get('retry',True):create_order('order-1',50)
  observed={'order':ORDERS['order-1']};assertions={'exactly-once':len(ORDERS['order-1']['charges'])==1}
 elif kind=='fault-injection':
  # Simulate timeout after a successful write, then retry to test idempotency.
  ORDERS.clear();create_order('order-1',50)
  try:raise TimeoutError('synthetic timeout after commit')
  except TimeoutError:create_order('order-1',50)
  observed={'order':ORDERS['order-1'],'injected_fault':'timeout_after_commit'}
  assertions={'exactly-once-after-timeout':len(ORDERS['order-1']['charges'])==1}
 else:raise ValueError('unsupported scenario kind')
 run_id=str(uuid4());blob=json.dumps(observed,sort_keys=True).encode();digest=hashlib.sha256(blob).hexdigest()
 (output/(digest+'.json')).write_bytes(blob)
 verdict='PASS' if all(assertions.values()) else 'FAIL'
 result={'run_id':run_id,'scenario':scenario,'verdict':verdict,'assertions':assertions,'evidence_sha256':digest,'created_at':utc()}
 (output/(run_id+'.json')).write_text(json.dumps(result,indent=2)+'\n')
 with sqlite3.connect(output/'history.sqlite3') as db:
  db.execute('CREATE TABLE IF NOT EXISTS history(run_id TEXT PRIMARY KEY,kind TEXT,verdict TEXT,digest TEXT,created_at TEXT)')
  db.execute('INSERT INTO history VALUES (?,?,?,?,?)',(run_id,kind,verdict,digest,result['created_at']))
 if graph is not None:
  graph.node('scenario:'+kind,'scenario','reference-v1',scenario,'fixture:scenario')
  graph.node('run:'+run_id,'run','reference-v1',{'verdict':verdict,'evidence_sha256':digest},'runner:'+run_id)
  graph.edge('scenario:'+kind,'run:'+run_id,'EXECUTED_AS','reference-v1','runner:'+run_id)
 return result
