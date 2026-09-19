"""SQLite-backed, versioned provenance graph; no LLM-derived facts accepted implicitly."""
import sqlite3, json
from pathlib import Path
class Graph:
 def __init__(self,path):
  self.path=str(path); Path(path).parent.mkdir(parents=True,exist_ok=True)
  with self.connect() as db:
   db.executescript("""CREATE TABLE IF NOT EXISTS nodes(id TEXT PRIMARY KEY,kind TEXT NOT NULL,version TEXT NOT NULL,properties TEXT NOT NULL,provenance TEXT NOT NULL);
   CREATE TABLE IF NOT EXISTS edges(source TEXT NOT NULL,target TEXT NOT NULL,relation TEXT NOT NULL,version TEXT NOT NULL,provenance TEXT NOT NULL,PRIMARY KEY(source,target,relation,version));""")
 def connect(self): return sqlite3.connect(self.path)
 def node(self,id,kind,version,properties,provenance):
  if not provenance: raise ValueError('provenance required')
  with self.connect() as db: db.execute('INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?)',(id,kind,version,json.dumps(properties,sort_keys=True),provenance))
 def edge(self,source,target,relation,version,provenance):
  if not provenance: raise ValueError('provenance required')
  with self.connect() as db:
   if db.execute('SELECT COUNT(*) FROM nodes WHERE id IN (?,?)',(source,target)).fetchone()[0]!=2: raise ValueError('unknown endpoint')
   db.execute('INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?)',(source,target,relation,version,provenance))
 def neighbors(self,id):
  with self.connect() as db: return db.execute('SELECT target,relation,version,provenance FROM edges WHERE source=?',(id,)).fetchall()
