import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "services" / "image-api" / "image_api" / "job_store.py"
SPEC = importlib.util.spec_from_file_location("gpu45_job_store", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)
JobStore = MODULE.JobStore


class JobStoreTests(unittest.TestCase):
    def test_imports_json_and_persists_transactionally(self):
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "jobs.json"
            json_path.write_text(json.dumps([{"id": "one", "status": "completed"}]), encoding="utf-8")
            store = JobStore(json_path)
            self.assertEqual(store.load()[0]["id"], "one")
            backups = list(json_path.parent.glob("jobs.json.migration-*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].stat().st_mode & 0o222, 0)
            store.save([{"id": "two", "status": "paused"}])
            self.assertEqual(JobStore(json_path).load(), [{"id": "two", "status": "paused"}])
            with closing(sqlite3.connect(json_path.with_suffix(".db"))) as connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")


if __name__ == "__main__":
    unittest.main()
