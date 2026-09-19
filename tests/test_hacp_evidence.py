"""Read-only HACP evidence export over a synthetic `.hacp/session.json`."""
import hashlib
import json
import tempfile
from pathlib import Path

from services.platform.hacp_evidence import export, main
from services.platform.hacp_mailbox import envelope

A, B = 'urn:hacp:agent:a', 'urn:hacp:agent:b'


def _project(root, *, senders=(A, B), tamper=False, bad_envelope=False):
    session = 's-0123456789abcdef'
    artifact = root / 'out.txt'
    artifact.write_text('frozen output\n')
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    messages = [envelope(session, s, B if s == A else A, 'hacp.skill.ask', {'text': 'hello from ' + s})
                for s in senders]
    if bad_envelope:
        messages.append({**messages[0], 'message_id': 'not-an-id'})
    state = {
        'format': 1,
        'session': {'session_id': session, 'state': 'active', 'participants': [A, B], 'close_reason': None},
        'peers': {'a': {'owns': ['out.txt'], 'task': 't'}, 'b': {'owns': [], 'task': 't'}},
        'messages': messages,
        'events': [{'time': '2026-09-19T00:00:00Z', 'peer': 'a', 'action': 'start'}],
        'contracts': {'c-1': {
            'proposer': 'a',
            'contract': {'contract_id': 'c-1', 'state': 'settled', 'task': {'owner': A},
                         'revisions': [{'number': 1, 'digest': 'rev1',
                                        'content': {'outputs': ['out.txt'], 'acceptance': ['true']}}]},
            'submissions': [{'against_revision': 'rev1', 'artifacts': ['art-1'], 'evidence': [], 'claim': 'done'}],
            'artifacts': [{'path': 'out.txt', 'record': {'artifact_id': 'art-1', 'digest': 'sha256:' + digest,
                                                         'size': 14, 'contract_revision': 'rev1'}}],
            'verifications': [{'verifier': B, 'against_revision': 'rev1', 'verdict': 'accept',
                               'artifacts': ['art-1'], 'checks': [{'name': 'true', 'passed': True, 'detail': ''}]}],
            'attempts': [{'id': 'v1', 'peer': 'b', 'status': 'complete',
                          'commands': [{'command': 'true', 'stdout': '', 'stderr': '', 'duration_ms': 3,
                                        'exit_code': 0, 'signal': None, 'timed_out': False}]}]}},
    }
    (root / '.hacp').mkdir()
    (root / '.hacp' / 'session.json').write_text(json.dumps(state))
    if tamper:
        artifact.write_text('changed after submission\n')
    return state


def test_export_reports_both_peers_contract_hashes_and_verdicts():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        _project(root)
        before = (root / '.hacp' / 'session.json').read_bytes()
        result = export(root)
        assert (root / '.hacp' / 'session.json').read_bytes() == before  # read-only
        assert result['both_participants_sent_messages'] is True
        assert result['invalid_envelopes'] == []
        contract = result['contracts'][0]
        assert contract['state'] == 'settled' and contract['owner'] == A
        assert contract['frozen_revisions'][0]['digest'] == 'rev1'
        assert contract['artifacts'][0]['unchanged_since_submission'] is True
        assert contract['verifications'][0]['verdict'] == 'accept'
        assert contract['verification_attempts'][0]['commands'][0]['exit_code'] == 0


def test_tampered_artifact_is_flagged_not_hidden():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        _project(root, tamper=True)
        artifact = export(root)['contracts'][0]['artifacts'][0]
        assert artifact['unchanged_since_submission'] is False
        assert artifact['current_sha256'] != artifact['submitted_sha256']


def test_cli_requires_both_peers_and_valid_envelopes():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        _project(root, senders=(A,))  # a self-sent conversation is not collaboration
        assert main(['--project', str(root), '--output', str(root / 'e.json'), '--require-both-peers']) == 1
        assert main(['--project', str(root), '--output', str(root / 'e.json')]) == 0
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        _project(root, bad_envelope=True)
        assert main(['--project', str(root), '--output', str(root / 'e.json')]) == 1
        assert export(root)['invalid_envelopes'][0]['message_id'] == 'not-an-id'
