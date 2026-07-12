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

    def test_higher_priority_preempts_only_preemptible_owner(self):
        with rm.connect() as db:
            db.execute(
                "INSERT INTO leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("tts", "book", "tts", 50, 1, "chunk", "active", rm.now(), rm.now(), rm.now(), None, "{}"),
            )
            original_active, original_post = rm.service_active, rm.post_local
            rm.service_active, rm.post_local = lambda _service: False, lambda _url, _payload=None: None
            try:
                self.assertTrue(rm.preempt_active(db, db.execute("SELECT * FROM leases WHERE lease_id='tts'").fetchone(), 100))
            finally:
                rm.service_active, rm.post_local = original_active, original_post
            self.assertEqual(db.execute("SELECT status FROM leases WHERE lease_id='tts'").fetchone()[0], "interrupted")
            self.assertEqual(db.execute("SELECT value FROM state WHERE key='resume_tts'").fetchone()[0], "1")

    def test_llm_grant_records_starting_transition(self):
        with rm.connect() as db:
            db.execute(
                "INSERT INTO leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("llm", "codex", "llm", 100, 0, "keep-loaded", "queued", rm.now(), None, None, None, "{}"),
            )
            rm.grant_next(db)
            self.assertEqual(db.execute("SELECT value FROM state WHERE key='transition'").fetchone()[0], "starting")

    def test_restoring_stopped_llm_records_transition(self):
        with rm.connect() as db:
            db.execute(
                "INSERT INTO leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("image", "image", "image", 70, 0, "restart", "active", rm.now(), rm.now(), rm.now(), None,
                 '{"stoppedServices":["llama-openai.service"]}'),
            )
            lease = db.execute("SELECT * FROM leases WHERE lease_id='image'").fetchone()
            original_action = rm.service_action
            rm.service_action = lambda _action, _service: None
            try:
                rm.restore_after_release(db, lease)
            finally:
                rm.service_action = original_action
            self.assertEqual(db.execute("SELECT value FROM state WHERE key='transition'").fetchone()[0], "restoring")


if __name__ == "__main__":
    unittest.main()
