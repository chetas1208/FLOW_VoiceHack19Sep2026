"""Onboarding an unfamiliar, token-gated app: discovery, approval gate, change selection, bug report."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from reference_apps.lending_library import lending_library
from services.universal_ui.onboard import approve, diff, onboard, select_regressions
from services.universal_ui.spec import validate

TOKEN = 'synthetic-onboarding-token'
ENV = {'QA_TARGET_TOKEN_ONBOARD': TOKEN}


def _onboard(root, *, broken=False, release='v2', auth=True):
    log = Path(root) / f'{release}.log'
    log.touch()
    with lending_library(log, broken=broken, token=TOKEN, release=release) as (origin, oracle):
        spec = {'id': 'lib', 'project_id': 'library', 'version': release, 'origin': origin}
        if auth:
            spec['auth_env'] = 'QA_TARGET_TOKEN_ONBOARD'
        return onboard(spec, root, max_pages=8), oracle, log


def test_discovery_separates_facts_from_hypotheses_and_skips_destructive_links():
    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, ENV):
        result, _, _ = _onboard(temp)
        assert {p['path'] for p in result['pages']} == {'/', '/catalog', '/loans', '/help'}
        assert all(p['http_status'] == 200 for p in result['pages'])
        assert result['skipped_unsafe_links'] == ['/account/delete']
        catalog = next(p for p in result['pages'] if p['path'] == '/catalog')
        assert catalog['forms'][0]['submit']['name'] == 'Reserve'
        assert [f['label'] for f in catalog['forms'][0]['fields']] == ['Member ID', 'Book']
        assert 'heading "Catalog"' in catalog['aria_snapshot']
        forms = [w for w in result['workflows'] if w['kind'] == 'form_submission']
        assert {w['variant']['book'] for w in forms} == {'b1', 'b2'}  # one draft per option, incl. last copy
        for workflow in forms:
            assert workflow['status'] == 'PROPOSED_REQUIRES_OWNER_APPROVAL'
            assert workflow['inferred']['confidence'] == 'unverified'
            assert workflow['discovered']['submit'] == 'Reserve'
        for workflow in result['workflows']:
            if workflow.get('runnable_without_approval'):
                validate(workflow['scenario'])


def test_token_is_required_and_not_persisted():
    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, ENV):
        result, _, _ = _onboard(temp, auth=False)
        assert {p['http_status'] for p in result['pages']} == {401}
        authed, _, _ = _onboard(temp)
        stored = (Path(temp) / 'onboarding' / 'library' / 'latest.json').read_text()
        assert TOKEN not in stored and 'QA_TARGET_TOKEN_ONBOARD' in stored


def test_mutating_draft_needs_explicit_owner_approval_and_an_oracle():
    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, ENV):
        result, oracle, _ = _onboard(temp)
        workflow = next(w for w in result['workflows'] if w['kind'] == 'form_submission')
        with pytest.raises(ValueError, match='allow_mutations'):
            validate(workflow['scenario'])
        with pytest.raises(ValueError, match='allow_mutations'):
            approve(workflow, {'oracle_origin': oracle, 'oracle_checks': [{}]})
        with pytest.raises(ValueError, match='oracle'):
            approve(workflow, {'allow_mutations': True})
        scenario = approve(workflow, {'allow_mutations': True, 'oracle_origin': oracle, 'oracle_checks': [
            {'oracle_path': '/state', 'pointer': '/reservations', 'operator': 'equals', 'expected': 1}]})
        validate(scenario)
        assert scenario['steps'][-1]['action'] == 'assert_oracle'


def test_version_diff_selects_changed_pages_and_previous_failures():
    with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, ENV):
        v2, _, _ = _onboard(temp, release='v2')
        v3, _, _ = _onboard(temp, release='v3')
        assert v3['changes']['pages_changed'] == ['/loans']
        assert v3['changes'] == diff(v2, v3)
        selection = select_regressions(v3['changes'], v3['workflows'], {'form-catalog-reserve-form-b2'})
        chosen = {x['id']: x['reasons'] for x in selection['selected']}
        assert chosen == {'nav-loans': ['page changed since v2'],
                          'form-catalog-reserve-form-b2': ['failed in a previous run']}


def test_end_to_end_onboarding_demo():
    """Separate process: the runner's OTLP exporter is configured once per process."""
    import json
    import subprocess
    import sys
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temp:
        output = Path(temp) / 'demo'
        code = f'from scripts.onboarding_demo import demo; demo({str(output)!r})'
        run = subprocess.run([sys.executable, '-c', code], cwd=repo, capture_output=True, text=True, timeout=180)
        assert run.returncode == 0, run.stderr[-2000:]
        result = json.loads((output / 'summary.json').read_text())
        assert result['all_checks_passed'], result['checks']
        report = (output / 'bug-report.md').read_text()
        assert 'The UI reported success while the independent state check disagreed.' in report
        assert 'synthetic-staging-token' not in report
