"""Wave 1 local, trusted reference fixture integration checks."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("wave1",ROOT/"services/runtime/wave1.py")
wave1=importlib.util.module_from_spec(spec)
spec.loader.exec_module(wave1)

class Wave1Tests(unittest.TestCase):
    def test_known_defects_are_detected_and_persisted(self):
        with tempfile.TemporaryDirectory() as temp:
            for kind in ("agentic","fullstack"):
                result=wave1.execute(kind,temp)
                self.assertEqual(result["verdict"]["status"],"FAIL")
                self.assertEqual(result["run"]["status"],"completed")
                self.assertEqual(len(result["trace_reference"]["trace_id"]),32)
                evidence=result["evidence"]
                self.assertTrue((Path(temp)/(evidence["sha256"]+".json")).exists())
                import hashlib
                self.assertEqual(hashlib.sha256((Path(temp)/(evidence["sha256"]+".json")).read_bytes()).hexdigest(),evidence["sha256"])
                for entity in ("run","verdict","evidence","trace-reference"):
                    record=json.loads((Path(temp)/f'{result["run"]["run_id"]}.{entity}.json').read_text())
                    self.assertEqual(record["run_id"],result["run"]["run_id"])
            with sqlite3.connect(Path(temp)/"runs.sqlite3") as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM runs WHERE verdict='FAIL'").fetchone()[0],2)

if __name__=="__main__":unittest.main()
