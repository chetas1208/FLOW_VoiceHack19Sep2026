"""Onboard an unfamiliar, owner-authorized web application.

Discovery is read-only. The result keeps two kinds of statement apart:

* ``discovered`` facts were observed in the rendered UI (pages, forms, fields,
  controls, the ARIA tree), with the page path they came from.
* ``inferred`` statements are hypotheses about business intent (for example
  "this form probably creates a record"). They are never used as expected results.

Workflow drafts are ordinary scenario documents for ``runner.execute``. Read-only
drafts validate and can run as they are. Mutating drafts are written with
``allow_mutations: false``, so ``spec.validate`` rejects them until an owner
approval (``approve``) supplies mutation consent and an independent state check.
"""
import copy
import hashlib
import json
import os
import re
from pathlib import Path

from services.universal_ui.discovery import discover
from services.universal_ui.spec import DANGEROUS, validate

SYNTHETIC = {'email': 'qa.synthetic@example.test', 'number': '1', 'tel': '5550100',
             'url': 'https://example.test/', 'date': '2030-01-01', 'password': None}
MAX_VARIANTS = 5
CARRY = ('project_id', 'version', 'origin', 'browser', 'viewport', 'fixture_relay',
         'timeout_ms', 'auth_env', 'propagate_trace')


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _name(*parts):
    return re.sub(r'[^A-Za-z0-9_-]+', '-', '-'.join(parts)).strip('-')[:60] or 'step'


def _field_locator(field):
    if field.get('test_id'): return {'by': 'test_id', 'value': field['test_id']}
    if field.get('label'): return {'by': 'label', 'value': field['label']}
    if field.get('id'): return {'by': 'id', 'value': field['id']}
    if field.get('name'): return {'by': 'css', 'value': f'[name={json.dumps(field["name"])}]'}
    return None


def _submit_locator(submit):
    if not submit: return None
    if submit.get('test_id'): return {'by': 'test_id', 'value': submit['test_id']}
    if submit.get('id'): return {'by': 'id', 'value': submit['id']}
    if submit.get('name'): return {'by': 'text', 'value': submit['name']}
    return None


def _synthetic(field):
    kind = (field.get('type') or 'text').lower()
    if kind in SYNTHETIC: return SYNTHETIC[kind]
    label = (field.get('label') or field.get('name') or '').lower()
    return 'qa-synthetic-001' if re.search(r'\bid\b|number|code', label) else 'QA synthetic'


def structure_digest(page):
    """Digest of UI structure only (no typed values), used to detect changed features."""
    return _digest({'headings': page.get('headings', []),
                    'forms': [{k: v for k, v in f.items()} for f in page.get('forms', [])],
                    'controls': [{k: c.get(k) for k in ('tag', 'role', 'type', 'label', 'test_id', 'id')}
                                 for c in page.get('controls', [])],
                    'links': sorted(page.get('discovered_links', []))})


def _navigation_draft(base, page):
    steps = [{'name': 'open', 'action': 'goto', 'path': page['path']},
             {'name': 'page_errors', 'action': 'assert_no_page_errors'},
             {'name': 'console_errors', 'action': 'assert_no_console_errors'},
             {'name': 'http_errors', 'action': 'assert_no_http_errors'},
             {'name': 'accessibility', 'action': 'audit_accessibility'}]
    if page.get('title'):
        # Observed current behaviour, recorded as a baseline, not a requirement.
        steps.insert(1, {'name': 'title_baseline', 'action': 'assert_title', 'expected': page['title']})
    return {**base, 'id': _name('nav', page['path'].strip('/') or 'home'), 'steps': steps}


def _form_drafts(base, page, form, index):
    submit = _submit_locator(form.get('submit'))
    fields = [f for f in form.get('fields', []) if _field_locator(f)]
    words = ' '.join([page['path'], (form.get('submit') or {}).get('name') or '', form.get('id') or '']).lower()
    destructive = any(word.strip() in words for word in DANGEROUS)
    if submit is None or destructive or any(f.get('type') == 'password' for f in fields):
        reason = ('no submit control' if submit is None else
                  'destructive label' if destructive else 'credential field: use an auth fixture')
        return [], reason
    selects = [f for f in fields if f.get('tag') == 'select' and f.get('options')]
    variants = [{}]
    if selects:
        # Boundary coverage: one draft per option of the first select (bounded).
        first = selects[0]
        variants = [{first['id'] or first['name']: option} for option in first['options'][:MAX_VARIANTS]]
    drafts = []
    for variant in variants:
        steps = [{'name': 'open', 'action': 'goto', 'path': page['path']}]
        for field in fields:
            key = field.get('id') or field.get('name')
            locator = _field_locator(field)
            if field.get('tag') == 'select':
                value = variant.get(key) or (field.get('options') or [None])[0]
                if value is None: continue
                steps.append({'name': _name('select', key or 'field'), 'action': 'select', 'locator': locator, 'value': value})
            elif (field.get('type') or '') in ('checkbox', 'radio'):
                steps.append({'name': _name('check', key or 'field'), 'action': 'check', 'locator': locator})
            else:
                steps.append({'name': _name('fill', key or 'field'), 'action': 'fill', 'locator': locator,
                              'value': _synthetic(field)})
        steps.append({'name': 'submit', 'action': 'click', 'locator': submit})
        for region in page.get('live_regions', [])[:1]:
            loc = ({'by': 'test_id', 'value': region['test_id']} if region.get('test_id') else
                   {'by': 'id', 'value': region['id']} if region.get('id') else None)
            if loc:
                steps.append({'name': 'outcome_visible', 'action': 'wait_for', 'locator': loc})
        steps += [{'name': 'console_errors', 'action': 'assert_no_console_errors'},
                  {'name': 'http_errors', 'action': 'assert_no_http_errors'}]
        suffix = '-'.join(str(v) for v in variant.values())
        scenario = {**base, 'id': _name('form', page['path'].strip('/') or 'home', form.get('id') or str(index), suffix),
                    'allow_mutations': False, 'steps': steps}
        drafts.append((scenario, variant))
    return drafts, None


def propose(inventory, spec):
    """Turn an inventory into workflow proposals and draft scenarios (no execution)."""
    base = {k: spec[k] for k in CARRY if k in spec}
    workflows = []
    for page in inventory['pages']:
        if page.get('status') == 'UNAVAILABLE':
            continue
        draft = _navigation_draft(base, page)
        workflows.append({'id': draft['id'], 'kind': 'navigation_smoke', 'path': page['path'],
                          'mutating': False, 'runnable_without_approval': True,
                          'discovered': {'title': page.get('title'), 'landmarks': page.get('landmarks', [])},
                          'inferred': None,
                          'expected_results_source': 'observed current behaviour (baseline), not a requirement',
                          'scenario': draft})
        for index, form in enumerate(page.get('forms', [])):
            drafts, skipped = _form_drafts(base, page, form, index)
            discovered = {'form_id': form.get('id'), 'method': form.get('method'),
                          'fields': [{k: f.get(k) for k in ('tag', 'type', 'label', 'required')} for f in form.get('fields', [])],
                          'submit': (form.get('submit') or {}).get('name')}
            if skipped:
                workflows.append({'id': _name('form', page['path'], str(index)), 'kind': 'form_submission',
                                  'path': page['path'], 'mutating': True, 'status': 'NOT_GENERATED',
                                  'reason': skipped, 'discovered': discovered})
                continue
            for scenario, variant in drafts:
                label = (form.get('submit') or {}).get('name') or 'submit'
                workflows.append({
                    'id': scenario['id'], 'kind': 'form_submission', 'path': page['path'], 'mutating': True,
                    'variant': variant, 'runnable_without_approval': False,
                    'status': 'PROPOSED_REQUIRES_OWNER_APPROVAL', 'discovered': discovered,
                    'inferred': {'hypothesis': f'"{label}" on {page["path"]} changes server-side state',
                                 'confidence': 'unverified', 'basis': 'form with submit control and live status region'
                                 if page.get('live_regions') else 'form with submit control'},
                    'owner_must_supply': ['mutation consent (allow_mutations)',
                                          'independent state check (oracle_origin + oracle_checks)',
                                          'expected outcome of the business rule'],
                    'scenario': scenario})
    return workflows


def approve(workflow, approval):
    """Merge an owner's explicit approval into a draft. Returns a runnable scenario.

    ``approval`` must grant mutations and give at least one independent oracle check;
    a UI message is never accepted as the only proof of success.
    """
    if workflow.get('status') == 'NOT_GENERATED':
        raise ValueError('workflow was not generated: ' + workflow.get('reason', ''))
    scenario = copy.deepcopy(workflow['scenario'])
    if workflow.get('mutating'):
        if approval.get('allow_mutations') is not True:
            raise ValueError('mutating workflow requires allow_mutations=true in the owner approval')
        if not approval.get('oracle_origin') or not approval.get('oracle_checks'):
            raise ValueError('mutating workflow requires an independent oracle check')
    for key in ('allow_mutations', 'oracle_origin', 'oracle_auth_env', 'log_file', 'log_messages',
                'propagate_trace', 'screenshots', 'version', 'auth_env'):
        if key in approval:
            scenario[key] = approval[key]
    for step in approval.get('ui_checks', []):
        scenario['steps'].insert(len(scenario['steps']) - 2, dict(step))
    for index, check in enumerate(approval.get('oracle_checks', [])):
        scenario['steps'].append({'name': _name('oracle', str(index)), 'action': 'assert_oracle', **check})
    if approval.get('log_file'):
        scenario['steps'].append({'name': 'server_errors', 'action': 'assert_no_server_errors'})
    return scenario


def diff(previous, current):
    """Compare two onboarding results; select workflows touching changed pages."""
    before = {p['path']: p.get('structure_sha256') for p in previous.get('pages', [])}
    after = {p['path']: p.get('structure_sha256') for p in current.get('pages', [])}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    touched = set(added) | set(changed)
    old_ids = {w['id'] for w in previous.get('workflows', [])}
    selected = [w['id'] for w in current.get('workflows', []) if w['path'] in touched]
    return {'from_version': previous.get('version'), 'to_version': current.get('version'),
            'pages_added': added, 'pages_removed': removed, 'pages_changed': changed,
            'pages_unchanged': sorted(p for p in set(before) & set(after) if before[p] == after[p]),
            'selected_workflows': selected,
            'new_workflow_candidates': [w['id'] for w in current.get('workflows', []) if w['id'] not in old_ids],
            'retired_workflows': sorted(old_ids - {w['id'] for w in current.get('workflows', [])})}


def select_regressions(changes, workflows, failing_ids=()):
    """Workflows to re-run for a new version: those on added/changed pages, plus every
    workflow that failed before (a fix must be proven, not assumed). Each carries its reason."""
    touched = set(changes.get('pages_added', [])) | set(changes.get('pages_changed', []))
    selected = []
    for workflow in workflows:
        reasons = []
        if workflow.get('path') in touched:
            reasons.append('page changed since ' + str(changes.get('from_version')))
        if workflow['id'] in failing_ids:
            reasons.append('failed in a previous run')
        if reasons:
            selected.append({'id': workflow['id'], 'reasons': reasons})
    unselected = [w['id'] for w in workflows if w['id'] not in {x['id'] for x in selected}]
    return {'selected': selected, 'not_selected': unselected,
            'note': 'unselected workflows are unaffected by observed UI structure changes; backend-only changes are invisible to this signal'}


def onboard(spec, output='.local-runs', *, max_pages=10, graph=None, drafts_dir=None):
    """Discover, propose, persist; compare with the last onboarding of this project."""
    inventory = discover(spec, max_pages=max_pages, graph=graph)
    for page in inventory['pages']:
        if page.get('status') != 'UNAVAILABLE':
            page['structure_sha256'] = structure_digest(page)
    workflows = propose(inventory, spec)
    project = spec.get('project_id', 'local')
    version = spec.get('version', 'unversioned')
    result = {'project_id': project, 'version': version, 'origin': inventory['origin'],
              'read_only_discovery': True, 'pages': inventory['pages'], 'truncated': inventory['truncated'],
              'skipped_unsafe_links': inventory.get('skipped_unsafe_links', []),
              'network_mode': inventory['network_mode'], 'workflows': workflows,
              'summary': {'pages': inventory['page_count'],
                          'forms': sum(len(p.get('forms', [])) for p in inventory['pages']),
                          'workflows': len(workflows),
                          'runnable_without_approval': sum(bool(w.get('runnable_without_approval')) for w in workflows),
                          'awaiting_owner_approval': sum(w.get('status') == 'PROPOSED_REQUIRES_OWNER_APPROVAL' for w in workflows)},
              'unverified': ['business intent of every form (inferred only)',
                             'routes reachable only after mutations or through non-link navigation',
                             'pages beyond max_pages' if inventory['truncated'] else 'none beyond discovered links']}
    for workflow in workflows:
        if workflow.get('runnable_without_approval'):
            validate(workflow['scenario'])  # read-only drafts must be executable as-is
    store = Path(output).resolve() / 'onboarding' / _name(project)
    store.mkdir(parents=True, exist_ok=True)
    latest = store / 'latest.json'
    if latest.exists():
        result['changes'] = diff(json.loads(latest.read_text()), result)
    data = json.dumps(result, indent=2, sort_keys=True)
    (store / (_name(version) + '.json')).write_text(data)
    latest.write_text(data)
    if drafts_dir:
        target = Path(drafts_dir)
        target.mkdir(parents=True, exist_ok=True)
        for workflow in workflows:
            if 'scenario' in workflow:
                (target / (workflow['id'] + '.json')).write_text(json.dumps(workflow['scenario'], indent=2))
    if graph is not None:
        for workflow in workflows:
            node = f'{project}:workflow:{workflow["id"]}'
            graph.node(node, 'workflow', version, {'kind': workflow['kind'], 'mutating': workflow['mutating'],
                       'status': workflow.get('status', 'PROPOSED')}, 'onboarding:' + spec['id'])
            graph.edge(f'{project}:ui:{workflow["path"]}', node, 'PROPOSES', version, 'onboarding:' + spec['id'])
    return result
