"""Offline HTML QA report. No scripts, external images, screenshots or raw DOM."""
import html
import json


def _escape(value):
    return html.escape(str(value), quote=True)


def render(run, observed):
    steps = observed.get('steps', [])
    findings = observed.get('findings', [])
    events = observed.get('events', [])
    def table(columns, rows):
        head = ''.join('<th>' + _escape(title) + '</th>' for title in columns)
        body = ''.join('<tr>' + ''.join('<td>' + _escape(x) + '</td>' for x in row) + '</tr>' for row in rows)
        return '<table><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table>'
    step_table = table(('Step', 'Action', 'Status', 'Time (ms)', 'Reason'),
                       ((r['step'], r['action'], r['status'], r['elapsed_ms'], r['reason']) for r in steps))
    finding_table = table(('Finding', 'Category', 'Step', 'Correlated events', 'Root cause proven?'),
                          ((r['fingerprint'], r['category'], r['step'],
                            ', '.join(str(n) for n in r['correlated_event_ids']), 'No') for r in findings))
    candidate_table = table(('Finding', 'Candidate file', 'Static route', 'Evidence'),
                            ((f['fingerprint'], candidate['file'],
                              candidate['method'] + ' ' + candidate['route'], candidate['route_provenance'])
                             for f in findings for candidate in f.get('source_candidates', [])))
    event_table = table(('Seq', 'Time (UTC)', 'Source', 'Level', 'Redacted message'),
                        ((e['seq'], e['at'], e['source'], e['level'], e.get('message', '[retention disabled]'))
                         for e in events))
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"/><meta name="viewport"
    content="width=device-width,initial-scale=1"/><meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"/>
    <title>AgentGraph QA — local UI report</title><style>
    body{font:16px system-ui,sans-serif;max-width:1100px;margin:36px auto;padding:0 18px;color:#18202a}
    h1{font-size:32px}h2{margin-top:30px}small{color:#516273}code{overflow-wrap:anywhere}
    table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:9px;
    border-bottom:1px solid #d7e0eb;vertical-align:top}th{background:#ecf2f7}
    .pill{display:inline-block;padding:6px 13px;background:#e8edf3;border-radius:16px;font-weight:700}
    .note{padding:12px;border-left:4px solid #9a6c18;background:#fff7dd}
    </style></head><body><h1>AgentGraph QA · UI run</h1>
    <p class="pill">''' + _escape(run['verdict']) + '''</p>
    <p>Scenario: <strong>''' + _escape(run['scenario_id']) + '''</strong><br/>
    Run: <code>''' + _escape(run['run_id']) + '''</code><br/>
    Trace: <code>''' + _escape(run['trace_id']) + '''</code><br/>
    Evidence SHA-256: <code>''' + _escape(run['evidence_sha256']) + '''</code></p>
    <p class="note">Diagnostic categories are heuristic correlations, not confirmed causes.
    Screenshots are stored privately and excluded from this report. Fixture-relay networking is
    synthetic and is not native-browser network validation.</p>
    <h2>Execution timeline</h2>''' + step_table + '''<h2>Findings</h2>''' + finding_table + \
    '''<h2>Candidate source locations (unconfirmed)</h2>''' + candidate_table + '''<h2>Concurrent evidence</h2>''' + event_table + '''<p><small>Event stream dropped: ''' + \
    _escape(observed.get('events_dropped', 0)) + '''. Generated from immutable hash-checked JSON evidence.</small></p></body></html>'''
