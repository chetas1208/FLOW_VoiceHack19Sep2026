"""SQLite durable queue for allowlisted, idempotent trusted local jobs.

Leases use fencing tokens to prevent a delayed worker from completing a job
claimed by another worker. This is at-least-once, not exactly-once delivery.
"""
import json
import sqlite3
import time
from uuid import uuid4
from pathlib import Path


class Queue:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL,
              owner TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
              result TEXT, lease_token TEXT, max_attempts INTEGER NOT NULL DEFAULT 3,
              last_error TEXT)''')
            columns = {r[1] for r in db.execute('PRAGMA table_info(jobs)')}
            for name, declaration in [('lease_token', 'TEXT'), ('max_attempts', 'INTEGER NOT NULL DEFAULT 3'),
                                      ('last_error', 'TEXT')]:
                if name not in columns:
                    db.execute(f'ALTER TABLE jobs ADD COLUMN {name} {declaration}')

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def submit(self, payload, max_attempts=3):
        if not 1 <= max_attempts <= 10:
            raise ValueError('max_attempts must be 1..10')
        identifier = str(uuid4())
        with self.db() as db:
            db.execute('INSERT INTO jobs(id,payload,status,max_attempts) VALUES (?,?,?,?)',
                       (identifier, json.dumps(payload), 'pending', max_attempts))
        return identifier

    def claim_fenced(self, owner, lease=30):
        if not owner or not 1 <= lease <= 3600:
            raise ValueError('owner and valid lease required')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            now = time.time()
            db.execute("UPDATE jobs SET status='failed',last_error='maximum lease attempts exhausted',owner=NULL,lease_token=NULL "
                       "WHERE status='running' AND lease_until < ? AND attempts>=max_attempts", (now,))
            row = db.execute("SELECT id,payload FROM jobs WHERE attempts < max_attempts AND "
                             "(status='pending' OR (status='running' AND lease_until < ?)) "
                             "ORDER BY rowid LIMIT 1", (now,)).fetchone()
            if not row:
                return None
            token = uuid4().hex
            db.execute("UPDATE jobs SET status='running',owner=?,lease_token=?,lease_until=?,attempts=attempts+1 "
                       "WHERE id=?", (owner, token, now+lease, row[0]))
            return row[0], json.loads(row[1]), token

    def claim(self, owner, lease=30):
        """Compatibility API. New workers should call claim_fenced."""
        claimed = self.claim_fenced(owner, lease)
        return claimed[:2] if claimed else None

    def complete(self, id, owner, result, token=None):
        condition = ' AND lease_token=?' if token is not None else ''
        args = [json.dumps(result), id, owner, time.time()]
        if token is not None:
            args.append(token)
        with self.db() as db:
            cursor = db.execute("UPDATE jobs SET status='completed',result=?,lease_until=NULL,lease_token=NULL "
                                "WHERE id=? AND owner=? AND status='running' AND lease_until>=?" + condition,
                                args)
            if cursor.rowcount != 1:
                raise PermissionError('job not owned, fencing token invalid, or lease expired')

    def heartbeat(self, id, owner, lease=30, token=None):
        condition = ' AND lease_token=?' if token is not None else ''
        args = [time.time()+lease, id, owner, time.time()]
        if token is not None:
            args.append(token)
        with self.db() as db:
            cursor = db.execute("UPDATE jobs SET lease_until=? WHERE id=? AND owner=? "
                                "AND status='running' AND lease_until>=?"+condition, args)
            if cursor.rowcount != 1:
                raise PermissionError('job lease lost')

    def fail(self, id, owner, message, token):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT attempts,max_attempts FROM jobs WHERE id=? AND owner=? "
                             "AND status='running' AND lease_token=? AND lease_until>=?",
                             (id, owner, token, time.time())).fetchone()
            if not row:
                raise PermissionError('job lease lost')
            status = 'failed' if row[0] >= row[1] else 'pending'
            db.execute('UPDATE jobs SET status=?,owner=NULL,lease_until=NULL,lease_token=NULL,last_error=? WHERE id=?',
                       (status, str(message)[:300], id))
            return status

    def cancel(self, id):
        with self.db() as db:
            cursor = db.execute("UPDATE jobs SET status='cancelled',owner=NULL,lease_until=NULL,lease_token=NULL "
                                "WHERE id=? AND status IN ('pending','running')", (id,))
            return cursor.rowcount == 1
