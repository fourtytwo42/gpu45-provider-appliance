import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("resource_manager.py")
SPEC = importlib.util.spec_from_file_location("resource_manager", MODULE_PATH)
rm = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(rm)


class ResourceManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        rm.DB_PATH = Path(self.temp.name) / "manager.db"
        rm.init_db()

    def tearDown(self):
        self.temp.cleanup()

    def test_priority_queue_grants_highest_priority_next(self):
        with rm.connect() as db:
            for job, priority in (("first", 50), ("codex", 100), ("image", 70)):
                db.execute(
                    "INSERT INTO leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (job, job, job, priority, 0, "restart", "queued", rm.now(), None, None, None, "{}"),
                )
            owner = rm.grant_next(db)
            self.assertEqual(owner["job_id"], "codex")

    def test_expired_active_lease_is_reclaimed(self):
        with rm.connect() as db:
            db.execute(
                "INSERT INTO leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("stale", "job", "tts", 50, 1, "chunk", "active", rm.now(), "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", None, "{}"),
            )
            self.assertEqual(rm.reclaim_expired(db), 1)
            self.assertEqual(db.execute("SELECT status FROM leases WHERE lease_id='stale'").fetchone()[0], "interrupted")


if __name__ == "__main__":
    unittest.main()
