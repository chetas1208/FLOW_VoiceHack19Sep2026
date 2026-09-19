"""CLI for reference suite and change-aware regression."""
import argparse,json
from pathlib import Path
from services.platform.regression import select,changed_since,FULL
from services.runtime.scenarios import run_scenario

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',default='.local-runs');p.add_argument('--changed-since');p.add_argument('--all',action='store_true');a=p.parse_args()
    kinds=FULL if a.all or not a.changed_since else select(changed_since(a.changed_since,Path(__file__).resolve().parents[2]))
    results=[run_scenario({'kind':k,'name':'demo'},a.output) for k in kinds]
    print(json.dumps({'executed':list(kinds),'results':results},indent=2))
    return 1 if any(r['verdict']=='FAIL' for r in results) else 0
if __name__=='__main__':raise SystemExit(main())
