"""Conservative Python AST discovery. Dynamic calls and other languages remain unknown."""
import ast, hashlib
from pathlib import Path
import importlib.util
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('qa_graph',ROOT/'services/graph/graph.py'); module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
def discover(repo,graph,version='local'):
 repo=Path(repo).resolve(); count=0
 for file in repo.rglob('*.py'):
  if any(p in {'.git','.venv','venv','node_modules','__pycache__'} for p in file.parts): continue
  try: tree=ast.parse(file.read_text(encoding='utf8'))
  except (SyntaxError,UnicodeError): continue
  rel=str(file.relative_to(repo)); fid='file:'+rel
  graph.node(fid,'file',version,{'path':rel},'ast:'+hashlib.sha256(file.read_bytes()).hexdigest())
  for item in ast.walk(tree):
   if isinstance(item,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
    ident=f'{fid}:{item.name}:{item.lineno}'
    graph.node(ident,'symbol',version,{'name':item.name,'line':item.lineno},f'ast:{rel}:{item.lineno}')
    graph.edge(fid,ident,'DEFINES',version,f'ast:{rel}:{item.lineno}');count+=1
 return count
