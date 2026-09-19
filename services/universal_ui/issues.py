"""Stable cross-run failure signatures; reporting does not assert root cause."""
import json
import re
import sqlite3
from pathlib import Path


class IssueIndex:
    def __init__(self, output):
        self.path = Path(output) / 'ui-findings.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS issues (
                fingerprint TEXT PRIMARY KEY,
                project_id TEXT NOT NULL, category TEXT NOT NULL,
                step TEXT NOT NULL, reason TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                occurrences INTEGER NOT NULL, latest_run_id TEXT NOT NULL,
                latest_trace_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS issue_runs (
                fingerprint TEXT NOT NULL, run_id TEXT NOT NULL,
                trace_id TEXT NOT NULL, observed_at TEXT NOT NULL,
                PRIMARY KEY(fingerprint,run_id));
            CREATE INDEX IF NOT EXISTS idx_issue_project ON issues(project_id,last_seen);
            ''')

    def connect(self): return sqlite3.connect(self.path, timeout=10)

    def add(self, record):
        with self.connect() as db:
            for finding in record['findings']:
                digest = finding['fingerprint']
                inserted = db.execute('INSERT OR IGNORE INTO issue_runs VALUES (?,?,?,?)',
                    (digest, record['run_id'], record['trace_id'], record['created_at'])).rowcount
                if not inserted: continue
                db.execute('''INSERT INTO issues VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        last_seen=excluded.last_seen,
                        occurrences=issues.occurrences+1,
                        latest_run_id=excluded.latest_run_id,
                        latest_trace_id=excluded.latest_trace_id''',
                    (digest, record['project_id'], finding['category'], finding['step'],
                     finding['reason'], record['created_at'], record['created_at'],
                     1, record['run_id'], record['trace_id']))

    def list(self, project_id=None, limit=50):
        if not 1 <= limit <= 100: raise ValueError('limit must be 1..100')
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute('SELECT * FROM issues' + (' WHERE project_id=?' if project_id else '') +
                              ' ORDER BY last_seen DESC LIMIT ?',
                              (project_id, limit) if project_id else (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get(self, fingerprint):
        if not re.fullmatch('[a-f0-9]{20}', fingerprint):
            raise ValueError('invalid finding fingerprint')
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            issue = db.execute('SELECT * FROM issues WHERE fingerprint=?', (fingerprint,)).fetchone()
            if issue is None: return None
            history = db.execute('SELECT run_id,trace_id,observed_at FROM issue_runs '
                                 'WHERE fingerprint=? ORDER BY observed_at DESC LIMIT 50',
                                 (fingerprint,)).fetchall()
        return {**dict(issue), 'runs': [dict(row) for row in history]}
