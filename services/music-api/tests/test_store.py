import tempfile
import unittest
from pathlib import Path

from music_api.store import MusicStore


class MusicStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MusicStore(Path(self.temp.name) / "music.db")
        self.store.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_job_lifecycle_and_retry(self):
        job = self.store.create_job("ace-xl-turbo-4b", "create", "text2music", {"caption": "test"})
        self.assertEqual(job["status"], "queued")
        self.store.update(str(job["id"]), status="failed", stage="failed", error="failure")
        retried = self.store.retry(str(job["id"]))
        self.assertEqual(retried["status"], "queued")
        self.assertIsNone(retried["error"])

    def test_recovery_uses_backend_policy(self):
        ace = self.store.create_job("ace-xl-turbo-4b", "create", "text2music", {})
        levo = self.store.create_job("levo2-large-amd", "create", "text2music", {})
        self.store.update(str(ace["id"]), status="running")
        self.store.update(str(levo["id"]), status="running")
        self.assertEqual(self.store.recover(), 2)
        self.assertEqual(self.store.get_job(str(ace["id"]))["recovery_state"], "restart")
        self.assertEqual(self.store.get_job(str(levo["id"]))["recovery_state"], "resume-phase")

    def test_orderly_shutdown_requeues_job_with_backend_policy(self):
        ace = self.store.create_job("ace-xl-turbo-4b", "create", "text2music", {})
        levo = self.store.create_job("levo2-large-amd", "reference", "reference", {})
        self.store.update(str(ace["id"]), status="running", process_pid=123)
        self.store.update(str(levo["id"]), status="running", process_pid=456)
        recovered_ace = self.store.mark_interrupted(str(ace["id"]))
        recovered_levo = self.store.mark_interrupted(str(levo["id"]))
        self.assertEqual((recovered_ace["status"], recovered_ace["recovery_state"]), ("queued", "restart"))
        self.assertEqual((recovered_levo["status"], recovered_levo["recovery_state"]), ("queued", "resume-phase"))
        self.assertIsNone(recovered_ace["process_pid"])

    def test_active_job_cannot_be_deleted(self):
        job = self.store.create_job("ace-xl-turbo-4b", "create", "text2music", {})
        self.store.update(str(job["id"]), status="running")
        with self.assertRaises(ValueError):
            self.store.delete(str(job["id"]))

    def test_eta_estimate_uses_completed_runtime_per_output_second(self):
        first = self.store.create_job("levo2-large-amd", "reference", "reference", {"duration": 10})
        second = self.store.create_job("levo2-large-amd", "reference", "reference", {"duration": 20})
        self.store.update(str(first["id"]), status="completed", metrics_json='{"generationSeconds":700}')
        self.store.update(str(second["id"]), status="completed", metrics_json='{"generationSeconds":1200}')
        self.assertEqual(self.store.estimate_seconds("levo2-large-amd", "reference", 10), 700)
        self.assertEqual(self.store.estimate_seconds("levo2-large-amd", "reference", 15), 950)
        self.assertIsNone(self.store.estimate_seconds("ace-xl-base-4b", "cover", 10))


if __name__ == "__main__":
    unittest.main()

