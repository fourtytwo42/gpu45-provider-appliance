import importlib.util
import tempfile
import unittest
from unittest import mock
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
            with mock.patch.object(rm, "transition_before_grant"):
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

    def test_long_transition_refresh_prevents_active_lease_reclamation(self):
        with rm.connect() as db:
            db.execute(
                "INSERT INTO leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("benchmark", "campaign", "benchmark", 10, 1, "restart-task", "active", rm.now(),
                 "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", None, "{}"),
            )
            rm.refresh_active_lease(db, "benchmark")
            self.assertEqual(rm.reclaim_expired(db), 0)
            self.assertEqual(db.execute("SELECT status FROM leases WHERE lease_id='benchmark'").fetchone()[0], "active")

    def test_locked_db_fails_fast_when_transition_lock_is_busy(self):
        busy_lock = mock.Mock()
        busy_lock.acquire.return_value = False
        original_lock = rm.LOCK
        rm.LOCK = busy_lock
        try:
            with self.assertRaisesRegex(TimeoutError, "another GPU transition"):
                with rm.locked_db(0.01):
                    self.fail("busy lock must not enter the database context")
        finally:
            rm.LOCK = original_lock
        busy_lock.release.assert_not_called()

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

    def test_benchmark_grant_keeps_loaded_llm(self):
        with rm.connect() as db:
            db.execute(
                "INSERT INTO leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("benchmark", "campaign", "benchmark", 10, 1, "restart-task", "queued", rm.now(), None, None, None, "{}"),
            )
            original_active, original_action = rm.service_active, rm.service_action
            calls = []
            rm.service_active = lambda _service: True
            rm.service_action = lambda action, service: calls.append((action, service))
            try:
                rm.grant_next(db)
            finally:
                rm.service_active, rm.service_action = original_active, original_action
            self.assertEqual(calls, [])
            self.assertEqual(db.execute("SELECT value FROM state WHERE key='transition'").fetchone()[0], "starting")

    def test_provider_restart_stops_then_starts_slow_service(self):
        calls = []
        with mock.patch.object(rm, "service_active", return_value=True), mock.patch.object(
            rm, "service_action", side_effect=lambda action, service: calls.append((action, service))
        ):
            rm.restart_service("llama-openai.service")
        self.assertEqual(
            calls,
            [("stop", "llama-openai.service"), ("start", "llama-openai.service")],
        )

    def test_provider_readiness_fails_fast_after_service_exit(self):
        with mock.patch.object(rm, "backend_ready", return_value=False), mock.patch.object(
            rm, "service_status", return_value="inactive"
        ):
            with self.assertRaisesRegex(RuntimeError, "stopped before becoming ready"):
                rm.wait_backend_ready(timeout=10, startup_grace=0)

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

    def test_idle_worker_stops_without_active_lease(self):
        with rm.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO state(key,value) VALUES(?,?)",
                ("worker:image:last_activity", "2000-01-01T00:00:00+00:00"),
            )
        stopped = []
        original_active, original_action = rm.service_active, rm.service_action
        rm.service_active = lambda service: service == rm.WORKER_SERVICES["image"]
        rm.service_action = lambda action, service: stopped.append((action, service))
        try:
            rm.reap_idle_workers_once(now_epoch=rm.datetime(2026, 1, 1, tzinfo=rm.timezone.utc).timestamp())
        finally:
            rm.service_active, rm.service_action = original_active, original_action
        self.assertEqual(stopped, [("stop", rm.WORKER_SERVICES["image"])])

    def test_active_lease_protects_idle_worker(self):
        with rm.connect() as db:
            db.execute(
                "INSERT INTO leases VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("image", "image", "image", 70, 0, "atomic", "active", rm.now(), rm.now(), rm.now(), None, "{}"),
            )
            db.execute(
                "INSERT OR REPLACE INTO state(key,value) VALUES(?,?)",
                ("worker:image:last_activity", "2000-01-01T00:00:00+00:00"),
            )
        stopped = []
        original_active, original_action = rm.service_active, rm.service_action
        rm.service_active = lambda service: service == rm.WORKER_SERVICES["image"]
        rm.service_action = lambda action, service: stopped.append((action, service))
        try:
            rm.reap_idle_workers_once(now_epoch=rm.datetime(2026, 1, 1, tzinfo=rm.timezone.utc).timestamp())
        finally:
            rm.service_active, rm.service_action = original_active, original_action
        self.assertEqual(stopped, [])


if __name__ == "__main__":
    unittest.main()
