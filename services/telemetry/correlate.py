"""Per-step correlation of a universal-UI run with browser, log and OTLP evidence.

Read-only join over what the runner already stored: the run record, its
content-addressed evidence (event stream) and ``telemetry.sqlite3`` written by
``services.telemetry.receiver``. Nothing here changes a verdict.

Every join is graded:

* ``trace_linked``: the item carries W3C trace context tying it to this run: a
  backend span whose parent is the step's ``qa.ui.step`` span or that shares the
  run's trace ID, or a log line containing the step's span ID or the run's trace ID.
* ``time_window``: the event arrived between the step's start and end sequence
  numbers. That is an observation of timing, not proof that the step caused it.
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

from services.engine.store import Store

TRACE_IN_TEXT = re.compile(r'\b([0-9a-f]{32})\b')
SPAN_IN_TEXT = re.compile(r'(?:span_id=|00-[0-9a-f]{32}-)([0-9a-f]{16})\b')


def _spans(output, trace_id):
    """Return (spans, status). status explains why spans may be missing."""
    path = Path(output) / 'telemetry.sqlite3'
    if not path.exists():
        return [], 'no telemetry.sqlite3 in output: OTLP receiver not writing here'
    try:
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
            rows = db.execute('SELECT span_id, parent_id, name, service, start_ns, end_ns, attributes '
                              'FROM spans WHERE trace_id=? ORDER BY start_ns', (trace_id,)).fetchall()
    except sqlite3.DatabaseError:
        return [], 'telemetry store unreadable'
    keys = ('span_id', 'parent_id', 'name', 'service', 'start_ns', 'end_ns', 'attributes')
    spans = [dict(zip(keys, row)) for row in rows]
    for span in spans:
        try:
            span['attributes'] = json.loads(span['attributes'])
        except (TypeError, ValueError):
            span['attributes'] = {}
    return spans, ('indexed' if spans else 'no spans indexed for this trace yet')


def _descendants(spans, root):
    children = {}
    for span in spans:
        children.setdefault(span['parent_id'], []).append(span)
    found, stack = [], [root]
    while stack:
        for child in children.get(stack.pop(), []):
            found.append(child)
            stack.append(child['span_id'])
    return found


def correlate(record, output):
    """Join one run record with its evidence and telemetry. Returns a JSON-able dict."""
    store = Store(output)
    observed = json.loads(store.evidence_bytes(record['evidence_sha256']))
    events = observed.get('events', [])
    trace_id = record['trace_id']
    spans, telemetry_status = _spans(output, trace_id)
    step_spans = {s['attributes'].get('qa.step.name'): s for s in spans if s['name'] == 'qa.ui.step'}
    qa_ids = {s['span_id'] for s in spans if s['name'].startswith('qa.ui.')}
    claimed = set()
    steps = []
    for entry in observed.get('steps', []):
        start, end = entry['event_seq_start'], entry['event_seq_end']
        window = [e for e in events if start < e['seq'] <= end and e['source'] != 'runner']
        step_span = step_spans.get(entry['step'])
        network, logs, other = [], [], []
        for event in window:
            item = {k: event[k] for k in ('seq', 'source', 'level', 'status', 'method', 'path') if k in event}
            item['join'] = 'time_window'
            if event['source'] == 'server_log':
                text = event.get('message', '')
                if step_span and step_span['span_id'] in SPAN_IN_TEXT.findall(text):
                    item['join'] = 'trace_linked'
                    item['trace_basis'] = 'step span_id in log line'
                elif trace_id in TRACE_IN_TEXT.findall(text):
                    item['join'] = 'trace_linked'
                    item['trace_basis'] = 'run trace_id in log line'
                elif 'message' not in event:
                    item['trace_basis'] = 'log message not retained (log_messages=false)'
                logs.append(item)
            elif event['source'] == 'network':
                network.append(item)
            else:
                other.append(item)
            claimed.add(event['seq'])
        backend = []
        if step_span:
            for span in _descendants(spans, step_span['span_id']):
                if span['span_id'] in qa_ids:
                    continue
                backend.append({'name': span['name'], 'service': span['service'], 'span_id': span['span_id'],
                                'parent_id': span['parent_id'], 'join': 'trace_linked',
                                'trace_basis': 'descendant of this step span',
                                'duration_ms': round(((span['end_ns'] or 0) - (span['start_ns'] or 0)) / 1e6, 3)})
        steps.append({'step': entry['step'], 'action': entry['action'], 'status': entry['status'],
                      'source': entry['source'], 'step_span_id': step_span['span_id'] if step_span else None,
                      'network': network, 'server_logs': logs, 'other_events': other,
                      'backend_spans': backend,
                      'trace_linked_count': sum(x['join'] == 'trace_linked' for x in logs + backend)})
    linked = {b['span_id'] for s in steps for b in s['backend_spans']}
    orphan_spans = [{'name': s['name'], 'service': s['service'], 'span_id': s['span_id'],
                     'join': 'trace_linked', 'trace_basis': 'same trace, parent not a step span'}
                    for s in spans if s['span_id'] not in qa_ids and s['span_id'] not in linked]
    unattributed = [{k: e[k] for k in ('seq', 'source', 'level') if k in e}
                    for e in events if e['seq'] not in claimed and e['source'] != 'runner']
    limits = []
    if telemetry_status != 'indexed':
        limits.append('backend span joins unavailable: ' + telemetry_status)
    elif not step_spans:
        limits.append('no qa.ui.step spans indexed: step span IDs unknown, only time-window joins possible')
    if not observed.get('trace_propagation_enabled'):
        limits.append('trace propagation disabled: backends could not receive step context')
    if not observed.get('event_messages_opted_in'):
        limits.append('log messages not retained: log lines cannot be trace-linked')
    if observed.get('events_dropped'):
        limits.append(f'{observed["events_dropped"]} events dropped by bounded stream')
    return {'run_id': record['run_id'], 'trace_id': trace_id, 'verdict': record['verdict'],
            'telemetry': telemetry_status, 'span_count': len(spans), 'steps': steps,
            'backend_spans_outside_steps': orphan_spans, 'unattributed_events': unattributed,
            'limits': limits,
            'note': 'trace_linked joins rest on propagated W3C context; time_window joins are timing observations only'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Per-step correlation of a stored UI run')
    parser.add_argument('run_id')
    parser.add_argument('--output', default='.local-runs', help='the runner output directory')
    args = parser.parse_args(argv)
    record = Store(args.output).get(args.run_id)
    if record is None:
        print(json.dumps({'error': 'unknown run_id'}), file=sys.stderr)
        return 2
    print(json.dumps(correlate(record, args.output), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
