"""Atomic redacted content-addressed evidence and SQLite run records."""
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SENSITIVE = re.compile(r'(password|passwd|secret|token|authorization|api[_-]?key|cookie|credential|private[_-]?key)', re.I)


def redact(obj):
    if isinstance(obj, dict):
        return {k: '[REDACTED]' if SENSITIVE.search(k) else redact(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def utc():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory):
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir(exist_ok=True)
        self.path = self.root / 'engine.sqlite3'
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS runs(
                    run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, scenario_id TEXT NOT NULL,
                    version TEXT NOT NULL, kind TEXT NOT NULL, verdict TEXT NOT NULL,
                    trace_id TEXT NOT NULL, digest TEXT NOT NULL, created_at TEXT NOT NULL,
                    details TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id, created_at);
            ''')

    def connection(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, run):
        sanitized = redact(run['observed'])
        blob = json.dumps(sanitized, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
        digest = hashlib.sha256(blob).hexdigest()
        path = self.evidence / (digest + '.json')
        if not path.exists():
            fd, tmp = tempfile.mkstemp(dir=self.evidence, prefix='.pending-')
            try:
                with os.fdopen(fd, 'wb') as output:
                    output.write(blob)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        result = {k: v for k, v in run.items() if k != 'observed'}
        result['evidence_sha256'] = digest
        with self.connection() as db:
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)', (
                result['run_id'], result['project_id'], result['scenario_id'], result['version'],
                result['kind'], result['verdict'], result['trace_id'], digest,
                result['created_at'], json.dumps(result, sort_keys=True)))
        return result

    def get(self, run_id, project_id=None):
        query = 'SELECT details FROM runs WHERE run_id=?' + (' AND project_id=?' if project_id else '')
        with self.connection() as db:
            row = db.execute(query, (run_id, project_id) if project_id else (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, project_id=None, limit=50):
        if not 1 <= limit <= 100:
            raise ValueError('limit must be 1–100')
        with self.connection() as db:
            rows = db.execute('SELECT details FROM runs' + (' WHERE project_id=?' if project_id else '') +
                              ' ORDER BY created_at DESC LIMIT ?', ((project_id, limit) if project_id else (limit,))).fetchall()
        return [json.loads(row[0]) for row in rows]

    def evidence_bytes(self, digest):
        if not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('invalid digest')
        path = self.evidence / (digest + '.json')
        blob = path.read_bytes()
        if hashlib.sha256(blob).hexdigest() != digest:
            raise IOError('evidence integrity failure')
        return blob
