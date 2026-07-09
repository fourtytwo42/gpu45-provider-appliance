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


if __name__ == "__main__":
    unittest.main()
