"""Universal UI QA CLI: execute or propose test scenarios from an approved origin."""
import argparse
import json
import os
from pathlib import Path

from services.graph.graph import Graph
from services.universal_ui.discovery import discover
from services.universal_ui.runner import execute


def main(argv=None):
    parser = argparse.ArgumentParser(description='Owner-authorized, evidence-backed UI QA')
    parser.add_argument('scenario', help='JSON scenario document')
    parser.add_argument('--output', default='.local-runs')
    parser.add_argument('--otlp-endpoint', default=os.getenv('QA_OTLP_TRACES_ENDPOINT'))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--discover', action='store_true', help='Read-only route/control inventory; never click')
    modes.add_argument('--auto-audit', action='store_true', help='Read-only browser health checks on discovered routes')
    parser.add_argument('--max-pages', type=int, default=10)
    parser.add_argument('--fail-on-verdict', action='store_true')
    parser.add_argument('--html-report', help='Write a local, redacted offline HTML report')
    args = parser.parse_args(argv)
    spec = json.loads(Path(args.scenario).read_text())
    graph = Graph(Path(args.output) / 'graph.sqlite3')
    if args.discover:
        result = discover(spec, max_pages=args.max_pages, graph=graph)
    elif args.auto_audit:
        from services.universal_ui.autopilot import audit
        result = audit(spec, args.output, max_pages=args.max_pages, local_files=True,
                       graph=graph, otlp_endpoint=args.otlp_endpoint)
    else:
        result = execute(spec, args.output, args.otlp_endpoint, local_files=True, graph=graph)
    if args.html_report and not args.discover and not args.auto_audit:
        from services.engine.store import Store
        from services.universal_ui.report import render
        html = render(result, json.loads(Store(args.output).evidence_bytes(result['evidence_sha256'])))
        target = Path(args.html_report)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as destination:
            destination.write(html)
    print(json.dumps(result, indent=2))
    if not args.discover and result['verdict'] == 'INFRA_ERROR': return 2
    if not args.discover and args.fail_on_verdict and result['verdict'] != 'PASS': return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
