#!/usr/bin/env python3
"""One command: benchmark, HACP wire demo, read-only graph discovery, summary."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.benchmark import benchmark
from services.platform.hacp_mailbox import collaboration_demo
from services.discovery.project import discover_project
from services.graph.graph import Graph


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',default='.local-runs/demo')
    p.add_argument('--repo',default='reference_apps')
    p.add_argument('--browser',action='store_true')
    args=p.parse_args()
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
    data={'benchmark':benchmark(root/'benchmark'),
          'collaboration':collaboration_demo(root/'collaboration'),
          'discovery':discover_project(args.repo,Graph(root/'graph.sqlite3'),
                                        project='demo',version='reference-v1')}
    if args.browser:
        from services.fullstack_qa.browser import verify_browser_retry
        data['browser']=verify_browser_retry()
    data['all_reference_expectations_met']=(
        data['benchmark']['known_defect_detection']==data['benchmark']['known_defect_total'] and
        data['benchmark']['false_failure_count']==0 and data['collaboration']['verified'] and
        (not args.browser or data['browser']['verdict']=='FAIL'))
    (root/'demo-report.json').write_text(json.dumps(data,indent=2)+'\n')
    print(json.dumps(data,indent=2))
    return 0 if data['all_reference_expectations_met'] else 1


if __name__=='__main__':
    raise SystemExit(main())
