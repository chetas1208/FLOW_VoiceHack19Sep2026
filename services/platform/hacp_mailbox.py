"""HACP/2.0 JSON envelope transport for trusted local peers.

Validates the schema from the user-supplied hacp 1.1.1 crate, participant
membership, canonical syntax, HMAC identity, and replay IDs. HACP's Rust core
remains the authority for the FULL contract state machine: this is a transport,
not a reimplementation of its lifecycle or proof of Rust conformance.
"""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from jsonschema import Draft7Validator

SCHEMA_PATH = Path(__file__).resolve().parents[2] / 'integrations/hacp/vendor/hacp-1.1.1/spec/schemas/envelope.json'
SCHEMA = json.loads(SCHEMA_PATH.read_text())
URN = re.compile(r'^urn:hacp:agent:[a-z0-9._-]{1,64}$')
MESSAGE = re.compile(r'^m-[a-f0-9]{12,}$')


def canonical(value):
    """HACP canonical JSON: integer-only, minimal sorted UTF-8, long control escapes."""
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, int):
        if not -(2**63) <= value <= 2**64-1:
            raise ValueError('HACP integer out of range')
        return str(value)
    if isinstance(value, str):
        return '"' + ''.join((f'\\u{ord(c):04x}' if ord(c) < 32 else
                              '\\"' if c == '"' else '\\\\' if c == '\\' else c)
                             for c in value) + '"'
    if isinstance(value, list):
        return '[' + ','.join(canonical(x) for x in value) + ']'
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise ValueError('HACP JSON object keys must be strings')
        return '{' + ','.join(canonical(k) + ':' + canonical(value[k])
                              for k in sorted(value, key=lambda s: s.encode('utf-8'))) + '}'
    raise ValueError('HACP values cannot contain floats or arbitrary types')


def envelope(session, sender, recipient, kind, body, in_reply_to=None):
    record = {'protocol': 'HACP/2.0', 'message_id': 'm-' + uuid4().hex,
              'session_id': session, 'from': sender, 'to': recipient,
              'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
              'kind': kind, 'body': body}
    if in_reply_to:
        record['in_reply_to'] = in_reply_to
    validate_envelope(record)
    return record


def validate_envelope(record):
    Draft7Validator(SCHEMA).validate(record)
    if record['protocol'] != 'HACP/2.0' or not record['session_id'] or not record['kind']:
        raise ValueError('invalid HACP protocol, session or kind')
    if not MESSAGE.fullmatch(record['message_id']) or not URN.fullmatch(record['from']) or not URN.fullmatch(record['to']):
        raise ValueError('invalid HACP message or identity')
    if record.get('in_reply_to') and not MESSAGE.fullmatch(record['in_reply_to']):
        raise ValueError('invalid reply reference')
    value = record['timestamp']
    if len(value) != 20 or datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%dT%H:%M:%SZ') != value:
        raise ValueError('noncanonical timestamp')
    canonical(record)
    return record


class Mailbox:
    def __init__(self, path, keys):
        """`keys` are generated outside model context and kept out of transcripts."""
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.keys = keys
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, opener TEXT, peer TEXT, active INTEGER);
              CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, session TEXT, sender TEXT,
                       recipient TEXT, content TEXT, signature TEXT, delivered INTEGER DEFAULT 0);
            ''')

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def open(self, session, opener, peer):
        if opener == peer or not URN.fullmatch(opener) or not URN.fullmatch(peer):
            raise ValueError('sessions require two distinct valid agent identities')
        if opener not in self.keys or peer not in self.keys:
            raise ValueError('both agents must be registered')
        with self.db() as db:
            db.execute('INSERT INTO sessions VALUES (?,?,?,1)', (session, opener, peer))

    def sign(self, message, who):
        """Called in peer trust context, never using an LLM-held key."""
        if who not in self.keys or message['from'] != who:
            raise PermissionError('sender identity mismatch')
        return hmac.new(self.keys[who], canonical(message).encode(), hashlib.sha256).hexdigest()

    def deliver(self, message, signature):
        validate_envelope(message)
        key = self.keys.get(message['from'])
        if not key or not hmac.compare_digest(hmac.new(key, canonical(message).encode(), hashlib.sha256).hexdigest(), signature):
            raise PermissionError('invalid message authentication')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            party = db.execute('SELECT opener,peer,active FROM sessions WHERE id=?', (message['session_id'],)).fetchone()
            if not party or not party[2] or {message['from'], message['to']} != set(party[:2]):
                raise PermissionError('invalid bilateral session or participant')
            try:
                db.execute('INSERT INTO messages(id,session,sender,recipient,content,signature) VALUES (?,?,?,?,?,?)',
                           (message['message_id'], message['session_id'], message['from'], message['to'], canonical(message), signature))
            except sqlite3.IntegrityError as exc:
                raise ValueError('replayed HACP message ID') from exc
        return message['message_id']

    def receive(self, session, recipient):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT id,content FROM messages WHERE session=? AND recipient=? AND delivered=0 ORDER BY rowid',
                              (session, recipient)).fetchall()
            for identifier, _ in rows:
                db.execute('UPDATE messages SET delivered=1 WHERE id=?', (identifier,))
        return [json.loads(body) for _, body in rows]

    def close(self, session, actor):
        with self.db() as db:
            row = db.execute('SELECT opener,peer FROM sessions WHERE id=?', (session,)).fetchone()
            if not row or actor not in row:
                raise PermissionError('only session participants may close')
            db.execute('UPDATE sessions SET active=0 WHERE id=?', (session,))


def collaboration_demo(output):
    """Two real local role handlers exchange signed HACP envelopes and verify bytes.

    This verifies envelope transport. The Rust contract state machine must be
    compiled and executed separately to claim full HACP conformance.
    """
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    a, b = 'urn:hacp:agent:orchestrator', 'urn:hacp:agent:graph-worker'
    keys = {a: secrets.token_bytes(32), b: secrets.token_bytes(32)}
    mailbox = Mailbox(root/'mailbox.sqlite3', keys)
    session = 'qa-' + uuid4().hex
    mailbox.open(session, a, b)
    request = envelope(session, a, b, 'contract.proposed',
                       {'task_id': 'graph-smoke', 'summary': 'produce verified JSON artifact'})
    mailbox.deliver(request, mailbox.sign(request, a))
    delivered = mailbox.receive(session, b)
    if len(delivered) != 1:
        raise RuntimeError('worker did not receive proposal')
    artifact = canonical({'capabilities': ['project', 'scenario']}).encode()
    digest = hashlib.sha256(artifact).hexdigest()
    path = root / (digest + '.json')
    path.write_bytes(artifact)
    submission = envelope(session, b, a, 'submission.delivered',
                          {'task_id': 'graph-smoke', 'sha256': digest, 'artifact': path.name},
                          in_reply_to=request['message_id'])
    mailbox.deliver(submission, mailbox.sign(submission, b))
    received = mailbox.receive(session, a)
    verified = len(received) == 1 and hashlib.sha256(path.read_bytes()).hexdigest() == received[0]['body']['sha256']
    verdict = envelope(session, a, b, 'verification.delivered',
                       {'accepted': verified, 'sha256': digest}, in_reply_to=submission['message_id'])
    mailbox.deliver(verdict, mailbox.sign(verdict, a))
    outcome = mailbox.receive(session, b)
    mailbox.close(session, a)
    return {'transport': 'HACP/2.0 schema-validated signed local mailbox',
            'verified': verified and len(outcome) == 1 and outcome[0]['body']['accepted'],
            'session_id': session, 'messages': 3, 'artifact_sha256': digest,
            'rust_contract_lifecycle_verified': False}


if __name__ == '__main__':
    import sys
    print(json.dumps(collaboration_demo(sys.argv[1] if len(sys.argv) > 1 else '.local-runs/collaboration'), indent=2))
