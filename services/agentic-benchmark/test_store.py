import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agentic_benchmark.model_catalog import discover_profiles
from agentic_benchmark.store import BenchmarkStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.schema = Path(__file__).with_name("schema.sql")
        self.store = BenchmarkStore(self.root / "agentic.db", self.schema)
        self.store.initialize()

    def tearDown(self):
        self.temp.cleanup()

    def test_campaign_persists_runs_and_recovers(self):
        profile = {"name": "model-a", "profileHash": "hash-a", "modelPath": "/models/a.gguf"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 2}
        campaign_id = self.store.create_campaign("Campaign", "custom", [profile], [suite])
        detail = self.store.campaign_detail(campaign_id)
        self.assertEqual(len(detail["runs"]), 1)
        with self.store.session() as db:
            db.execute("UPDATE campaigns SET status='running' WHERE id=?", (campaign_id,))
            db.execute("UPDATE runs SET status='running' WHERE campaign_id=?", (campaign_id,))
        self.store.initialize()
        recovered = self.store.campaign_detail(campaign_id)
        self.assertEqual(recovered["campaign"]["status"], "queued")
        self.assertEqual(recovered["runs"][0]["status"], "queued")

    def test_model_discovery_uses_served_profiles_and_hashes_settings(self):
        app_db = self.root / "appliance.db"
        model = self.root / "model.gguf"
        model.write_bytes(b"model")
        db = sqlite3.connect(app_db)
        db.executescript("""
          CREATE TABLE LaunchProfile(name TEXT,description TEXT,modelPath TEXT,ctxSize INTEGER,backend TEXT);
          CREATE TABLE ModelAsset(path TEXT,served INTEGER,servedAlias TEXT);
        """)
        db.execute("INSERT INTO LaunchProfile VALUES(?,?,?,?,?)", ("profile", "desc", str(model), 262144, "rocm"))
        db.execute("INSERT INTO ModelAsset VALUES(?,?,?)", (str(model), 1, "model-alias"))
        db.commit(); db.close()
        profiles = discover_profiles(app_db)
        self.assertEqual(profiles[0]["servedAlias"], "model-alias")
        self.assertEqual(len(profiles[0]["profileHash"]), 64)
        self.assertTrue(profiles[0]["modelAvailable"])


if __name__ == "__main__":
    unittest.main()
