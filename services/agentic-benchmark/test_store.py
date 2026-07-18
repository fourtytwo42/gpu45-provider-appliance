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

    def test_pause_cancel_retry_and_exports(self):
        profile = {"name": "model-a", "profileHash": "hash-a", "modelPath": "/models/a.gguf"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Control", "custom", [profile], [suite])
        runnable = self.store.next_runnable()
        assert runnable is not None
        run = self.store.begin_run(runnable["id"], None)
        self.store.ensure_tasks(run["id"], ["task-one"])
        task = self.store.next_task(run["id"])
        assert task is not None
        self.store.begin_task(task["id"])
        self.assertTrue(self.store.retry_infrastructure_task(task["id"], "retry"))
        self.assertFalse(self.store.retry_infrastructure_task(task["id"], "retry again"))
        artifact = self.store.add_artifact(campaign_id, run["id"], task["id"], "log", "campaign/run/log.txt", b"hello")
        self.assertIsNotNone(self.store.artifact(campaign_id, artifact["id"]))
        self.assertIsNone(self.store.artifact("wrong-campaign", artifact["id"]))
        self.assertEqual(1, len(self.store.export_rows(campaign_id)["artifacts"]))
        self.assertTrue(self.store.set_campaign_action(campaign_id, "pause"))
        self.assertEqual("paused", self.store.apply_pending_control(campaign_id, run["id"]))
        self.assertTrue(self.store.set_campaign_action(campaign_id, "resume"))
        self.assertTrue(self.store.set_campaign_action(campaign_id, "cancel"))
        self.assertEqual("cancelled", self.store.apply_pending_control(campaign_id, run["id"]))

    def test_cancel_marks_running_task_cancelled(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Cancel running", "custom", [profile], [suite])
        runnable = self.store.next_runnable()
        assert runnable is not None
        run = self.store.begin_run(runnable["id"], None)
        self.store.ensure_tasks(run["id"], ["task-one"])
        task = self.store.next_task(run["id"])
        assert task is not None
        self.store.begin_task(task["id"])
        self.store.set_campaign_action(campaign_id, "cancel")
        self.assertEqual("cancelled", self.store.apply_pending_control(campaign_id, run["id"]))
        with self.store.session() as db:
            status = db.execute("SELECT status FROM tasks WHERE id=?", (task["id"],)).fetchone()[0]
        self.assertEqual("cancelled", status)

    def test_cancelled_paused_campaign_finishes_without_runner_wakeup(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Cancel paused", "custom", [profile], [suite])
        with self.store.session() as db:
            db.execute("UPDATE campaigns SET status='paused',pause_requested=1 WHERE id=?", (campaign_id,))
            db.execute("UPDATE runs SET status='interrupted' WHERE campaign_id=?", (campaign_id,))
        self.assertTrue(self.store.set_campaign_action(campaign_id, "cancel"))
        detail = self.store.campaign_detail(campaign_id)
        self.assertEqual("cancelled", detail["campaign"]["status"])
        self.assertEqual("cancelled", detail["runs"][0]["status"])

    def test_pending_profile_runs_keep_the_same_model_warm(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suites = [
            {"id": "suite-a", "manifestHash": "suite-a-hash", "taskCount": 1},
            {"id": "suite-b", "manifestHash": "suite-b-hash", "taskCount": 1},
        ]
        campaign_id = self.store.create_campaign("Warm model", "custom", [profile], suites)
        runs = self.store.campaign_detail(campaign_id)["runs"]
        first, second = runs
        self.assertTrue(self.store.has_pending_profile_runs(campaign_id, "model-a", first["id"]))
        with self.store.session() as db:
            db.execute("UPDATE runs SET status='completed' WHERE id=?", (second["id"],))
        self.assertFalse(self.store.has_pending_profile_runs(campaign_id, "model-a", first["id"]))

    def test_completed_common_campaign_promotes_top_three_once(self):
        profiles = [{"name": f"model-{i}", "profileHash": f"hash-{i}", "modelPath": f"/models/{i}.gguf"} for i in range(4)]
        common_ids = ["bfcl-v4-local", "tau-text-base", "swe-verified-mini50", "terminal-bench-2"]
        common_suites = [{"id": item, "manifestHash": f"hash-{item}", "taskCount": 1} for item in common_ids]
        campaign_id = self.store.create_campaign("Common", "common", profiles, common_suites)
        with self.store.session() as db:
            db.execute("UPDATE campaigns SET status='completed' WHERE id=?", (campaign_id,))
            for index, profile in enumerate(profiles):
                db.execute("UPDATE runs SET status='completed',score=? WHERE campaign_id=? AND profile_name=?", (1.0 - index * 0.1, campaign_id, profile["name"]))
        qualification_ids = ["swe-bench-verified-500", "tau-three-trial-reliability", "bfcl-failed-category-rerun", "gpu45-codex-acceptance"]
        qualification_suites = [{"id": item, "manifestHash": f"hash-{item}", "taskCount": 1} for item in qualification_ids]
        first = self.store.promote_top_three(campaign_id, profiles, qualification_suites)
        second = self.store.promote_top_three(campaign_id, profiles, qualification_suites)
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        promoted = self.store.campaign_detail(str(first))
        self.assertEqual("top-three-qualification", promoted["campaign"]["preset"])
        self.assertEqual(12, len(promoted["runs"]))

    def test_manual_infrastructure_retry_requeues_failed_task(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Retry", "custom", [profile], [suite])
        runnable = self.store.next_runnable()
        run = self.store.begin_run(runnable["id"], None)
        self.store.ensure_tasks(run["id"], ["task-one"])
        task = self.store.next_task(run["id"])
        self.store.begin_task(task["id"])
        self.store.complete_task(task["id"], False, 10, "infrastructure_failure", "Docker failed")
        self.assertEqual(1, self.store.retry_campaign_infrastructure(campaign_id))
        retried = self.store.next_task(run["id"])
        self.assertEqual(task["id"], retried["id"])
        self.assertEqual("queued", retried["status"])

    def test_manual_infrastructure_retry_preserves_completed_task_counts(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 2}
        campaign_id = self.store.create_campaign("Retry partial", "custom", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)
        self.store.ensure_tasks(run["id"], ["first", "second"])
        first = self.store.next_task(run["id"])
        self.store.begin_task(first["id"])
        self.store.complete_task(first["id"], True, 10)
        second = self.store.next_task(run["id"])
        self.store.begin_task(second["id"])
        self.store.complete_task(second["id"], False, 10, "infrastructure_failure", "transport failed")

        self.assertEqual(1, self.store.retry_campaign_infrastructure(campaign_id))
        retried_run = self.store.campaign_detail(campaign_id)["runs"][0]
        self.assertEqual("queued", retried_run["status"])
        self.assertEqual(1, retried_run["completed_tasks"])
        self.assertEqual(1, retried_run["passed_tasks"])
        self.assertEqual(0, retried_run["failed_tasks"])

    def test_run_infrastructure_failure_retries_before_failing(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Retry run", "custom", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)

        self.assertTrue(self.store.retry_run_infrastructure(run["id"], "resource transition"))
        self.assertEqual("interrupted", self.store.campaign_detail(campaign_id)["runs"][0]["status"])
        self.assertTrue(self.store.retry_run_infrastructure(run["id"], "resource transition"))
        self.assertFalse(self.store.retry_run_infrastructure(run["id"], "resource transition"))

    def test_manual_retry_requeues_failed_run_before_any_task_completes(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Retry failed run", "custom", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)
        self.store.fail_run(run["id"], "resource manager transition")

        self.assertEqual(1, self.store.retry_campaign_infrastructure(campaign_id))
        self.assertEqual("interrupted", self.store.campaign_detail(campaign_id)["runs"][0]["status"])

    def test_ensure_tasks_replaces_obsolete_task_definitions(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Task migration", "custom", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)
        self.store.ensure_tasks(run["id"], ["category"])
        old = self.store.next_task(run["id"])
        self.store.complete_task(old["id"], False, 1, "infrastructure_failure")

        self.store.ensure_tasks(run["id"], ["category::case-0", "category::case-1"])

        with self.store.session() as db:
            tasks = db.execute("SELECT external_task_id FROM tasks WHERE run_id=? ORDER BY external_task_id", (run["id"],)).fetchall()
            run_state = db.execute("SELECT expected_tasks,completed_tasks,failed_tasks FROM runs WHERE id=?", (run["id"],)).fetchone()
        self.assertEqual(["category::case-0", "category::case-1"], [row[0] for row in tasks])
        self.assertEqual(2, run_state["expected_tasks"])
        self.assertEqual(0, run_state["completed_tasks"])
        self.assertEqual(0, run_state["failed_tasks"])

    def test_discovered_suite_total_applies_to_every_campaign_model(self):
        profiles = [
            {"name": "model-a", "profileHash": "hash-a"},
            {"name": "model-b", "profileHash": "hash-b"},
        ]
        suite = {"id": "dynamic-suite", "manifestHash": "suite-hash", "taskCount": 0}
        campaign_id = self.store.create_campaign("Fair totals", "common", profiles, [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)

        self.store.ensure_tasks(run["id"], ["task-1", "task-2", "task-3"])

        detail = self.store.campaign_detail(campaign_id)
        self.assertEqual([3, 3], [item["expected_tasks"] for item in detail["runs"]])

    def test_interrupted_run_resumes_before_later_queued_run(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suites = [
            {"id": "suite-a", "manifestHash": "hash-a", "taskCount": 1},
            {"id": "suite-b", "manifestHash": "hash-b", "taskCount": 1},
        ]
        campaign_id = self.store.create_campaign("Recovery order", "custom", [profile], suites)
        with self.store.session() as db:
            runs = db.execute("SELECT id,suite_id FROM runs WHERE campaign_id=? ORDER BY rowid", (campaign_id,)).fetchall()
            db.execute("UPDATE campaigns SET status='queued' WHERE id=?", (campaign_id,))
            db.execute("UPDATE runs SET status='queued' WHERE campaign_id=?", (campaign_id,))
            db.execute("UPDATE runs SET status='interrupted' WHERE id=?", (runs[0]["id"],))

        runnable = self.store.next_runnable()

        self.assertEqual(runs[0]["id"], runnable["id"])


if __name__ == "__main__":
    unittest.main()
