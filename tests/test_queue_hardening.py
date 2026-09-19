from pathlib import Path
import sqlite3
import tempfile
import time
import pytest
from services.runtime.queue import Queue
from services.runtime.worker import work


def test_fencing_prevents_stale_worker_completion_and_retry():
    with tempfile.TemporaryDirectory() as temp:
        q = Queue(Path(temp)/'q.sqlite3')
        id = q.submit({'kind': 'agentic'}, max_attempts=3)
        first = q.claim_fenced('same-owner', lease=1)
        with q.db() as db:
            db.execute('UPDATE jobs SET lease_until=? WHERE id=?',(time.time()-1,id))
        second = q.claim_fenced('same-owner', lease=20)
        assert second[0]==id and second[2]!=first[2]
        with pytest.raises(PermissionError):
            q.complete(id,'same-owner',{},token=first[2])
        q.complete(id,'same-owner',{'status':'ok'},token=second[2])
        assert q.claim_fenced('other') is None


def test_retry_limit_and_cancel():
    with tempfile.TemporaryDirectory() as temp:
        q=Queue(Path(temp)/'q.sqlite3')
        id=q.submit({'kind':'bad-kind'},max_attempts=2)
        assert work(q, temp)['verdict']=='INFRA_ERROR'
        assert work(q, temp)['verdict']=='INFRA_ERROR'
        assert work(q, temp) is None
        with q.db() as db:
            assert db.execute('SELECT status,attempts FROM jobs WHERE id=?',(id,)).fetchone()==('failed',2)
        pending=q.submit({'kind':'agentic'})
        assert q.cancel(pending)
        assert not q.cancel(pending)
        assert q.claim_fenced('a') is None
