import json
import os
import tempfile
import unittest
from pathlib import Path

from tts_api import store


class SqliteStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original = store.API_DATA_DIR
        store.API_DATA_DIR = self.temp.name

    def tearDown(self):
        store.API_DATA_DIR = self.original
        self.temp.cleanup()

    def test_imports_json_once_and_keeps_read_only_backup(self):
        source = Path(self.temp.name) / store.VOICES_JSON
        source.write_text(json.dumps([{"id": "v1", "name": "Alice"}]), encoding="utf-8")
        self.assertEqual(store.load_voices()[0]["name"], "Alice")
        backups = list(Path(self.temp.name).glob("voices.json.migration-*.bak"))
        self.assertEqual(len(backups), 1)
        source.write_text("[]", encoding="utf-8")
        self.assertEqual(store.load_voices()[0]["id"], "v1")

    def test_save_replaces_records_transactionally(self):
        store.save_models([{"id": "m1", "status": "ready"}])
        store.save_models([{"id": "m2", "status": "training"}])
        self.assertEqual(store.load_models(), [{"id": "m2", "status": "training"}])
        with store._connect_store() as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_audiobook_items_are_normalized_and_summary_is_compact(self):
        store.save_audiobook_jobs([{
            "id": "book-1",
            "status": "completed",
            "total_chunks": 2,
            "completed_chunks": 2,
            "failed_chunks": 0,
            "chunks": [
                {"index": 0, "status": "completed", "text": "One."},
                {"index": 1, "status": "flagged", "text": "Two."},
            ],
        }])
        with store._connect_store() as db:
            parent = json.loads(db.execute(
                "SELECT payload_json FROM records WHERE store_name='audiobook_jobs' AND record_id='book-1'"
            ).fetchone()[0])
            self.assertNotIn("chunks", parent)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM audiobook_chunks WHERE job_id='book-1'"
            ).fetchone()[0], 2)

        summary = store.load_snapshot(include_items=False)["audiobookJobs"][0]
        self.assertTrue(summary["items_truncated"])
        self.assertEqual(summary["chunks"], [])
        full = store.get_audiobook_job_by_id("book-1")
        self.assertFalse(full["items_truncated"])
        self.assertEqual([item["text"] for item in full["chunks"]], ["One.", "Two."])

        store.update_audiobook_chunk("book-1", 1, status="completed", text="Two fixed.")
        updated = store.get_audiobook_job_by_id("book-1")
        self.assertEqual(updated["completed_chunks"], 2)
        self.assertEqual(updated["chunks"][1]["text"], "Two fixed.")

    def test_active_presentation_keeps_slides_in_summary(self):
        store.save_presentation_jobs([{
            "id": "deck-1",
            "status": "running",
            "total_slides": 1,
            "completed_slides": 0,
            "failed_slides": 0,
            "slides": [{"index": 0, "status": "running", "text": "Welcome."}],
        }])
        summary = store.load_snapshot(include_items=False)["presentationJobs"][0]
        self.assertFalse(summary["items_truncated"])
        self.assertEqual(summary["slides"][0]["text"], "Welcome.")


if __name__ == "__main__":
    unittest.main()
