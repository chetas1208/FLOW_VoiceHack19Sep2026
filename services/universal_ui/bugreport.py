"""Reproducible Markdown bug report from a stored UI run. Observations, verified
outcomes and hypotheses are kept in separate sections; nothing is called a root cause."""
import json


def render(record, scenario, correlation=None, *, cli='python -m services.universal_ui.cli'):
    failed = [a for a in record.get('assertions', []) if a['status'] == 'FAIL']
    ui_claims = [a for a in record.get('assertions', []) if a['source'] == 'dom' and a['status'] == 'PASS']
    lines = [f"# {record['verdict']}: {scenario['id']} ({record['project_id']} {record['version']})", '',
             f"- Run: `{record['run_id']}`  Trace: `{record['trace_id']}`",
             f"- Evidence (sha256, content-addressed): `{record['evidence_sha256']}`", '',
             '## Verified (independent evidence)', '']
    lines += [f"- Step `{a['step']}` ({a['source']}): {a['reason']}" for a in failed] or ['- No failed independent checks.']
    lines += ['', '## Observed (UI claims that passed)', '']
    lines += [f"- Step `{a['step']}`: {a['reason']}" for a in ui_claims] or ['- None.']
    if ui_claims and any(a['source'] == 'oracle' for a in failed):
        lines += ['', '> The UI reported success while the independent state check disagreed.']
    lines += ['', '## Correlated runtime evidence', '']
    if correlation:
        for step in correlation['steps']:
            items = ([f"{n.get('method')} {n.get('path')} -> {n.get('status')} ({n['join']})" for n in step['network']] +
                     [f"server log {l['level']} ({l['join']})" for l in step['server_logs']] +
                     [f"span {b['service']}/{b['name']} ({b['join']})" for b in step['backend_spans']])
            if items:
                lines.append(f"- `{step['step']}` [{step['status']}]: " + '; '.join(items))
        for limit in correlation['limits']:
            lines.append(f'- Limit: {limit}')
    else:
        lines.append('- No correlation available.')
    lines += ['', '## Hypotheses (unconfirmed)', '']
    for finding in record.get('findings', []):
        lines.append(f"- `{finding['category']}` at step `{finding['step']}` "
                     f"(fingerprint `{finding['fingerprint']}`, root_cause_confirmed={finding['root_cause_confirmed']})")
    if correlation:
        for step in correlation['steps']:
            names = {b['name'] for b in step['backend_spans']}
            if any(n.startswith('POST') for n in names) and not any(n.startswith('db.') for n in names):
                lines.append(f"- Step `{step['step']}`: a backend request span exists with no database-write child span. "
                             'This is consistent with a write that was acknowledged but not committed; it is not proof.')
    lines += ['', '## Reproduce', '', 'Save the scenario below as `scenario.json` against the same app version, then run:', '',
              f'```sh\n{cli} scenario.json --output .local-runs --fail-on-verdict\n```', '',
              '```json', json.dumps(scenario, indent=2), '```', '']
    return '\n'.join(lines)
