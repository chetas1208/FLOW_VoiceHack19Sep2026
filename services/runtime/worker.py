"""Fenced local worker for allowlisted fixture scenarios; never execute user code."""
import argparse
import json
from pathlib import Path
from uuid import uuid4
from services.runtime.queue import Queue
from services.runtime.scenarios import run_scenario


def work(queue, output, owner=None):
    owner = owner or ('worker-' + uuid4().hex)
    claimed = queue.claim_fenced(owner)
    if claimed is None:
        return None
    identifier, scenario, token = claimed
    try:
        if scenario.get('kind') not in ('agentic', 'fullstack', 'fault-injection'):
            raise ValueError('unsupported scenario kind')
        result = run_scenario(scenario, output)
        queue.complete(identifier, owner, result, token=token)
        return result
    except Exception as exc:
        queue.fail(identifier, owner, type(exc).__name__ + ': trusted fixture worker failed', token)
        return {'job_id': identifier, 'verdict': 'INFRA_ERROR', 'reason': type(exc).__name__}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='.local-runs/jobs.sqlite3')
    parser.add_argument('--output', default='.local-runs')
    parser.add_argument('--submit', choices=['agentic', 'fullstack', 'fault-injection'])
    args = parser.parse_args()
    queue = Queue(args.db)
    if args.submit:
        print(json.dumps({'job_id': queue.submit({'kind': args.submit})}))
    else:
        print(json.dumps(work(queue, args.output) or {'status': 'idle'}, indent=2))
