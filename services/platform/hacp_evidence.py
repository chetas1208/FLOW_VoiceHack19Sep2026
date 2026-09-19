"""Read-only evidence export for a two-peer HACP session kept by the `hacp` CLI.

The `hacp` CLI (hacp-skill, built on `hacp::v2`) keeps session state in
`<project>/.hacp/session.json`. This module never writes, locks or repairs that
directory. It reports what the record shows:

* every message envelope checked against the vendored HACP/2.0 envelope schema;
* which participant URNs actually sent messages (collaboration needs both);
* each contract's state, frozen revision digests, submissions, artifact hashes
  and verification verdicts;
* whether each submitted artifact still has the submitted sha256 on disk.

A matching hash shows artifact integrity, not software correctness. Correctness
evidence is the verifier's acceptance-command results, reported alongside.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from services.platform.hacp_mailbox import validate_envelope


def _sha256(path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _artifacts(root, entry):
    """hacp-skill StoredArtifact = {path, record: hacp::v2 Artifact{digest, size, ...}}."""
    found = []
    for artifact in entry.get('artifacts', []):
        record = artifact.get('record', {})
        name, digest = artifact.get('path'), str(record.get('digest', ''))
        if not name or not digest:
            continue
        digest = digest.removeprefix('sha256:')
        current = _sha256(root / name)
        found.append({'path': name, 'artifact_id': record.get('artifact_id'), 'size': record.get('size'),
                      'contract_revision': record.get('contract_revision'),
                      'submitted_sha256': digest, 'current_sha256': current,
                      'unchanged_since_submission': current == digest})
    return found


def _verifications(entry):
    """hacp::v2 Verification records plus the CLI's measured acceptance-command attempts."""
    records = [{'verifier': v.get('verifier'), 'against_revision': v.get('against_revision'),
                'verdict': v.get('verdict'), 'artifacts': v.get('artifacts', []),
                'checks': [{k: c.get(k) for k in ('name', 'passed')} for c in v.get('checks', [])]}
               for v in entry.get('verifications', [])]
    attempts = [{'attempt_id': a.get('id'), 'peer': a.get('peer'), 'status': a.get('status'),
                 'commands': [{'command': c.get('command'), 'exit_code': c.get('exit_code'),
                               'timed_out': c.get('timed_out'), 'duration_ms': c.get('duration_ms')}
                              for c in a.get('commands', [])]}
                for a in entry.get('attempts', [])]
    return records, attempts


def export(project):
    root = Path(project).resolve()
    path = root / '.hacp' / 'session.json'
    state = json.loads(path.read_text())
    session = state.get('session', {})
    participants = session.get('participants', [])
    messages, invalid, senders = [], [], {}
    for record in state.get('messages', []):
        try:
            validate_envelope(record)
            ok = True
        except Exception as exc:  # schema, identity or canonical-form violation
            ok = False
            invalid.append({'message_id': record.get('message_id'), 'error': type(exc).__name__})
        senders[record.get('from')] = senders.get(record.get('from'), 0) + 1
        messages.append({'message_id': record.get('message_id'), 'from': record.get('from'),
                         'to': record.get('to'), 'kind': record.get('kind'),
                         'timestamp': record.get('timestamp'), 'in_reply_to': record.get('in_reply_to'),
                         'text': (record.get('body') or {}).get('text'), 'schema_valid': ok})
    contracts = []
    for contract_id, entry in state.get('contracts', {}).items():
        contract = entry.get('contract', {})
        verifications, attempts = _verifications(entry)
        contracts.append({
            'contract_id': contract_id,
            'owner': contract.get('task', {}).get('owner'),
            'proposer': entry.get('proposer'),
            'state': contract.get('state'),
            'frozen_revisions': [{'number': r.get('number'), 'digest': r.get('digest'),
                                  'outputs': (r.get('content') or {}).get('outputs'),
                                  'acceptance': (r.get('content') or {}).get('acceptance')}
                                 for r in contract.get('revisions', [])],
            'submissions': entry.get('submissions', []),
            'artifacts': _artifacts(root, entry),
            'verifications': verifications,
            'verification_attempts': attempts,
        })
    both = bool(participants) and all(senders.get(p, 0) > 0 for p in participants)
    return {'source': str(path.relative_to(root)),
            'session_id': session.get('session_id'), 'session_state': session.get('state'),
            'close_reason': session.get('close_reason'), 'participants': participants,
            'peers': state.get('peers', {}), 'messages_by_sender': senders,
            'both_participants_sent_messages': both,
            'message_count': len(messages), 'invalid_envelopes': invalid,
            'messages': messages, 'contracts': contracts,
            'events': [{'time': e.get('time'), 'peer': e.get('peer'), 'action': e.get('action')}
                       for e in state.get('events', [])],
            'integrity_note': 'sha256 equality shows the artifact bytes are unchanged; it does not show correctness'}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Export read-only HACP collaboration evidence')
    parser.add_argument('--project', default='.')
    parser.add_argument('--output', help='write JSON here (default: stdout)')
    parser.add_argument('--require-both-peers', action='store_true',
                        help='exit 1 unless every participant sent at least one message')
    args = parser.parse_args(argv)
    result = export(args.project)
    text = json.dumps(result, indent=2, sort_keys=True) + '\n'
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    else:
        sys.stdout.write(text)
    summary = {k: result[k] for k in ('session_id', 'session_state', 'messages_by_sender',
                                      'both_participants_sent_messages', 'message_count')}
    summary['invalid_envelopes'] = len(result['invalid_envelopes'])
    summary['contracts'] = {c['contract_id']: c['state'] for c in result['contracts']}
    print(json.dumps(summary), file=sys.stderr)
    if result['invalid_envelopes']:
        return 1
    if args.require_both_peers and not result['both_participants_sent_messages']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
