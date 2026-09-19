"""Conservative change-impact selection: unknown changes always run full suite."""
from pathlib import Path
import subprocess

FULL=('agentic','fullstack','fault-injection')
def select(changed_paths):
    paths=set(changed_paths)
    if not paths:return FULL
    if any(p.startswith(('contracts/','services/runtime/','services/platform/','infra/')) for p in paths):return FULL
    selected=set()
    for p in paths:
        if p.startswith(('reference_apps/agentic/','services/agentic_qa/')):selected.add('agentic')
        elif p.startswith(('reference_apps/fullstack/','services/fullstack_qa/')):selected.update(('fullstack','fault-injection'))
        elif p.startswith(('docs/','tests/','.github/')):return FULL
        else:return FULL
    return tuple(k for k in FULL if k in selected) or FULL

def changed_since(base,root):
    # No shell; explicit git args. A missing base fails closed.
    result=subprocess.run(['git','-C',str(Path(root).resolve()),'diff','--name-only',base,'--'],capture_output=True,text=True,check=True)
    return tuple(p for p in result.stdout.splitlines() if p)
