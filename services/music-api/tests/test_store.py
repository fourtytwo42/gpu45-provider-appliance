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

    def test_active_job_cannot_be_deleted(self):
        job = self.store.create_job("ace-xl-turbo-4b", "create", "text2music", {})
        self.store.update(str(job["id"]), status="running")
        with self.assertRaises(ValueError):
            self.store.delete(str(job["id"]))


if __name__ == "__main__":
    unittest.main()

