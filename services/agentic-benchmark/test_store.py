import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agentic_benchmark.model_catalog import discover_profiles
from agentic_benchmark.store import BenchmarkStore, now


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

    def test_latest_model_results_returns_the_newest_common_result_per_profile(self):
        profiles = [
            {"name": "model-a", "profileHash": "hash-a", "modelPath": "/models/a.gguf"},
            {"name": "model-b", "profileHash": "hash-b", "modelPath": "/models/b.gguf"},
        ]
        suite_ids = ["bfcl-v4-local", "tau-text-base", "swe-verified-mini50", "terminal-bench-2"]
        suites = [{"id": suite_id, "manifestHash": f"hash-{suite_id}", "taskCount": 2} for suite_id in suite_ids]
        older_id = self.store.create_campaign("Older", "common", profiles, suites)
        newer_id = self.store.create_campaign("Newer", "common", [profiles[0]], suites)
        with self.store.session() as db:
            db.execute("UPDATE campaigns SET status='completed',created_at='2026-01-01T00:00:00Z',completed_at='2026-01-01T01:00:00Z' WHERE id=?", (older_id,))
            db.execute("UPDATE campaigns SET status='running',created_at='2026-01-02T00:00:00Z' WHERE id=?", (newer_id,))
            db.execute(
                "UPDATE runs SET status='completed',expected_tasks=2,completed_tasks=2,passed_tasks=1,failed_tasks=1,score=0.5 WHERE campaign_id=?",
                (older_id,),
            )
            db.execute(
                "UPDATE runs SET status='running',expected_tasks=2,completed_tasks=1,passed_tasks=1,score=0.5 WHERE campaign_id=?",
                (newer_id,),
            )

        results = {row["profileName"]: row for row in self.store.latest_model_results()}

        self.assertEqual(newer_id, results["model-a"]["campaignId"])
        self.assertEqual("running", results["model-a"]["status"])
        self.assertEqual(4, results["model-a"]["completedTasks"])
        self.assertIsNone(results["model-a"]["compositeScore"])
        self.assertEqual(older_id, results["model-b"]["campaignId"])
        self.assertEqual("completed", results["model-b"]["status"])
        self.assertEqual(0.5, results["model-b"]["compositeScore"])

    def test_latest_model_results_includes_the_saved_agent_system_reference(self):
        profile = {
            "name": "reference-codex-gpt-5.6-sol-medium",
            "displayName": "Codex GPT-5.6 Sol Medium",
            "profileHash": "reference-hash",
            "executionMode": "external-openai",
        }
        suite_scores = {
            "bfcl-efficiency-v1": (4, 1.0),
            "tau-efficiency-v1": (3, 2 / 3),
            "swe-efficiency-v1": (2, 0.5),
            "terminal-efficiency-v1": (2, 0.5),
        }
        suites = [
            {"id": suite_id, "manifestHash": f"hash-{suite_id}", "taskCount": task_count}
            for suite_id, (task_count, _score) in suite_scores.items()
        ]
        campaign_id = self.store.create_campaign("Codex reference", "agent-system-reference-v1", [profile], suites)
        with self.store.session() as db:
            db.execute(
                "UPDATE campaigns SET status='completed',completed_at='2026-01-03T01:00:00Z' WHERE id=?",
                (campaign_id,),
            )
            db.execute("UPDATE runs SET track='reference' WHERE campaign_id=?", (campaign_id,))
            for suite_id, (task_count, score) in suite_scores.items():
                passed = round(task_count * score)
                db.execute(
                    "UPDATE runs SET status='completed',expected_tasks=?,completed_tasks=?,passed_tasks=?,"
                    "failed_tasks=?,score=? WHERE campaign_id=? AND suite_id=?",
                    (task_count, task_count, passed, task_count - passed, score, campaign_id, suite_id),
                )

        result = next(
            row
            for row in self.store.latest_model_results()
            if row["profileName"] == profile["name"]
        )

        self.assertEqual("Codex GPT-5.6 Sol Medium", result["displayName"])
        self.assertEqual("agent-system-reference", result["systemType"])
        self.assertEqual(11, result["expectedTasks"])
        self.assertEqual(8, result["passedTasks"])
        self.assertEqual(0.625, result["compositeScore"])
        self.assertEqual(1.0, result["suites"]["bfcl-v4-local"]["score"])

    def test_full_reference_reuses_exact_common_snapshots_and_reports_interaction_rates(self):
        local_profile = {"name": "local", "profileHash": "local-hash"}
        suite_counts = {
            "bfcl-v4-local": 36,
            "tau-text-base": 18,
            "swe-verified-mini50": 8,
            "terminal-bench-2": 8,
        }
        common_suites = [
            {
                "id": suite_id,
                "manifestHash": f"saved-hash-{suite_id}",
                "taskCount": task_count,
                "savedSelection": f"exact-{suite_id}",
            }
            for suite_id, task_count in suite_counts.items()
        ]
        source_id = self.store.create_campaign("Common", "common", [local_profile], common_suites)
        reference = {
            "name": "reference-codex",
            "displayName": "Codex GPT-5.6 Sol Medium",
            "profileHash": "reference-hash",
            "executionMode": "external-openai",
        }

        reference_id = self.store.create_reference_common_campaign(source_id, [reference])
        duplicate_id = self.store.create_reference_common_campaign(source_id, [reference])

        self.assertEqual(reference_id, duplicate_id)
        detail = self.store.campaign_detail(str(reference_id))
        self.assertEqual("agent-system-common-v1", detail["campaign"]["preset"])
        self.assertEqual({"reference"}, {run["track"] for run in detail["runs"]})
        self.assertEqual(70, sum(int(run["expected_tasks"]) for run in detail["runs"]))
        for run in detail["runs"]:
            snapshot = json.loads(run["suite_snapshot_json"])
            self.assertEqual(f"exact-{run['suite_id']}", snapshot["savedSelection"])

        legacy_id = self.store.create_campaign(
            "Legacy reference",
            "agent-system-reference-v1",
            [reference],
            [{"id": "bfcl-efficiency-v1", "manifestHash": "legacy", "taskCount": 1}],
        )
        with self.store.session() as db:
            db.execute("UPDATE runs SET track='reference' WHERE campaign_id=?", (legacy_id,))
            for run in db.execute(
                "SELECT id,suite_id,expected_tasks FROM runs WHERE campaign_id=?",
                (reference_id,),
            ):
                expected = int(run["expected_tasks"])
                db.execute(
                    "UPDATE runs SET status='completed',completed_tasks=?,passed_tasks=?,"
                    "failed_tasks=?,score=0.5 WHERE id=?",
                    (expected, expected // 2, expected - expected // 2, run["id"]),
                )
                task_id = f"task-{run['suite_id']}"
                db.execute(
                    "INSERT INTO tasks(id,run_id,external_task_id,status,passed,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (task_id, run["id"], "case", "completed", 1, now(), now()),
                )
                db.execute(
                    "INSERT INTO task_measurements("
                    "task_id,attempt,active_inference_ms,response_calls,invalid_calls,prompt_tokens,"
                    "completion_tokens,measurement_status,created_at,updated_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (task_id, 1, 1000, 1, 0, 100, 25, "complete", now(), now()),
                )
            db.execute(
                "UPDATE campaigns SET status='completed',completed_at=? WHERE id=?",
                (now(), reference_id),
            )

        matching = [
            row
            for row in self.store.latest_model_results()
            if row["profileName"] == reference["name"]
        ]

        self.assertEqual(1, len(matching))
        result = matching[0]
        self.assertEqual(reference_id, result["campaignId"])
        self.assertEqual(70, result["expectedTasks"])
        self.assertEqual(0.5, result["compositeScore"])
        self.assertEqual(100.0, result["estimatedPromptTokensPerSecond"])
        self.assertEqual(25.0, result["estimatedOutputTokensPerSecond"])
        self.assertEqual(4000, result["interactionDurationMs"])
        self.assertEqual("agentic-api-interaction", result["throughputMethod"])

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

    def test_interrupted_task_uses_a_new_measurement_attempt(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Attempt", "custom", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)
        self.store.ensure_tasks(run["id"], ["task-one"])
        task = self.store.next_task(run["id"])
        with self.store.session() as db:
            db.execute("UPDATE tasks SET status='interrupted' WHERE id=?", (task["id"],))

        restarted = self.store.begin_task(task["id"])

        self.assertEqual(2, restarted["attempt"])

    def test_reference_campaign_runs_before_older_local_work(self):
        local_profile = {"name": "model-a", "profileHash": "hash-a"}
        local_suite = {"id": "suite-a", "manifestHash": "suite-a", "taskCount": 1}
        self.store.create_campaign("Older local work", "smoke", [local_profile], [local_suite])
        reference_profile = {
            "name": "reference-codex",
            "profileHash": "reference-hash",
            "executionMode": "external-openai",
        }
        reference_suite = {"id": "suite-reference", "manifestHash": "suite-reference", "taskCount": 1}
        reference_id = self.store.create_campaign(
            "Codex reference",
            "agent-system-reference-v1",
            [reference_profile],
            [reference_suite],
        )

        runnable = self.store.next_runnable()

        self.assertIsNotNone(runnable)
        self.assertEqual(reference_id, runnable["campaign_id"])

    def test_request_metrics_are_correlated_and_deduplicated(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Metrics", "custom", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)
        self.store.ensure_tasks(run["id"], ["task-one"])
        task = self.store.begin_task(self.store.next_task(run["id"])["id"])
        payload = {
            "campaignId": campaign_id,
            "runId": run["id"],
            "taskId": task["id"],
            "attempt": task["attempt"],
            "requestId": "request-one",
            "apiPath": "/v1/responses",
            "statusCode": 200,
            "promptTokens": 30,
            "completionTokens": 10,
            "durationMs": 123,
            "toolCalls": 2,
            "usageSource": "response",
            "completed": True,
        }

        self.assertTrue(self.store.record_request_metric(payload))
        self.assertFalse(self.store.record_request_metric(payload))
        with self.store.session() as db:
            metric = db.execute("SELECT * FROM request_metrics WHERE task_id=?", (task["id"],)).fetchone()
        self.assertEqual(30, metric["prompt_tokens"])
        self.assertEqual(10, metric["completion_tokens"])
        self.assertEqual(2, metric["tool_calls"])

        with self.assertRaisesRegex(ValueError, "does not match"):
            self.store.record_request_metric({**payload, "requestId": "request-two", "runId": "wrong"})

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

    def test_completed_common_campaign_creates_one_efficiency_panel(self):
        profiles = [{"name": f"model-{i}", "profileHash": f"hash-{i}", "modelPath": f"/models/{i}.gguf"} for i in range(4)]
        common_ids = ["bfcl-v4-local", "tau-text-base", "swe-verified-mini50", "terminal-bench-2"]
        common_suites = [{"id": item, "manifestHash": f"hash-{item}", "taskCount": 1} for item in common_ids]
        campaign_id = self.store.create_campaign("Common", "common", profiles, common_suites)
        with self.store.session() as db:
            db.execute("UPDATE campaigns SET status='completed' WHERE id=?", (campaign_id,))
            for index, profile in enumerate(profiles):
                db.execute("UPDATE runs SET status='completed',score=? WHERE campaign_id=? AND profile_name=?", (1.0 - index * 0.1, campaign_id, profile["name"]))
        suite_ids = ["bfcl-efficiency-v1", "tau-efficiency-v1", "swe-efficiency-v1", "terminal-efficiency-v1"]
        suites = [{"id": item, "manifestHash": f"hash-{item}", "taskCount": count} for item, count in zip(suite_ids, (4, 3, 2, 2))]

        first = self.store.create_efficiency_campaign(campaign_id, profiles, suites)
        second = self.store.create_efficiency_campaign(campaign_id, profiles, suites)

        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        panel = self.store.campaign_detail(str(first))
        self.assertEqual("efficiency-v1", panel["campaign"]["preset"])
        self.assertEqual(12, len(panel["runs"]))
        self.assertEqual({"model-0", "model-1", "model-2"}, {run["profile_name"] for run in panel["runs"]})

    def test_reference_campaign_uses_fixed_panel_without_entering_local_ranking(self):
        local_profile = {"name": "local", "profileHash": "local-hash"}
        common_ids = ["bfcl-v4-local", "tau-text-base", "swe-verified-mini50", "terminal-bench-2"]
        common_suites = [{"id": item, "manifestHash": f"hash-{item}", "taskCount": 1} for item in common_ids]
        source_id = self.store.create_campaign("Common", "common", [local_profile], common_suites)
        reference = {
            "name": "reference-codex",
            "displayName": "Codex GPT-5.6 Sol Medium",
            "profileHash": "reference-hash",
            "model": "gpt-5.6-sol",
            "reasoningEffort": "medium",
            "executionMode": "external-openai",
            "endpointUrl": "http://127.0.0.1:30003",
        }
        suite_ids = list(("bfcl-efficiency-v1", "tau-efficiency-v1", "swe-efficiency-v1", "terminal-efficiency-v1"))
        suites = [{"id": item, "manifestHash": f"hash-{item}", "taskCount": count} for item, count in zip(suite_ids, (4, 3, 2, 2))]

        reference_id = self.store.create_reference_campaign(source_id, [reference], suites)
        duplicate_id = self.store.create_reference_campaign(source_id, [reference], suites)

        self.assertEqual(reference_id, duplicate_id)
        detail = self.store.campaign_detail(str(reference_id))
        self.assertEqual("agent-system-reference-v1", detail["campaign"]["preset"])
        self.assertEqual([], detail["ranking"])
        self.assertEqual({"reference"}, {run["track"] for run in detail["runs"]})
        with self.store.session() as db:
            for run in db.execute("SELECT id,suite_id FROM runs WHERE campaign_id=?", (reference_id,)):
                db.execute("UPDATE runs SET status='completed',score=1.0,expected_tasks=1,completed_tasks=1,passed_tasks=1 WHERE id=?", (run["id"],))
                task_id = f"task-{run['suite_id']}"
                db.execute(
                    "INSERT INTO tasks(id,run_id,external_task_id,status,passed,prompt_tokens,completion_tokens,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (task_id, run["id"], "case", "completed", 1, 100, 20, now(), now()),
                )
                db.execute(
                    "INSERT INTO task_measurements(task_id,attempt,wall_duration_ms,active_inference_ms,response_calls,tool_calls,prompt_tokens,completion_tokens,measurement_status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (task_id, 1, 1000, 800, 1, 1, 100, 20, "complete", now(), now()),
                )
            db.execute("UPDATE campaigns SET status='completed' WHERE id=?", (reference_id,))

        report = self.store.efficiency_report(source_id)
        row = report["referenceRows"][0]
        self.assertEqual(1.0, row["panelScore"])
        self.assertEqual(4, row["successes"])
        self.assertEqual(120.0, row["tokensPerSolve"])
        self.assertFalse(row["energyAvailable"])

    def test_reference_campaign_supersedes_changed_configuration(self):
        local_profile = {"name": "local", "profileHash": "local-hash"}
        common_ids = ["bfcl-v4-local", "tau-text-base", "swe-verified-mini50", "terminal-bench-2"]
        source_id = self.store.create_campaign(
            "Common", "common", [local_profile],
            [{"id": item, "manifestHash": f"hash-{item}", "taskCount": 1} for item in common_ids],
        )
        suites = [
            {"id": item, "manifestHash": f"hash-{item}", "taskCount": count}
            for item, count in zip(
                ("bfcl-efficiency-v1", "tau-efficiency-v1", "swe-efficiency-v1", "terminal-efficiency-v1"),
                (4, 3, 2, 2),
            )
        ]
        original = self.store.create_reference_campaign(
            source_id,
            [{"name": "reference-codex", "profileHash": "reference-v1"}],
            suites,
        )
        updated_suites = [{**suite, "manifestHash": suite["manifestHash"] + "-v2"} for suite in suites]

        replacement = self.store.create_reference_campaign(
            source_id,
            [{"name": "reference-codex", "profileHash": "reference-v2"}],
            updated_suites,
        )
        duplicate = self.store.create_reference_campaign(
            source_id,
            [{"name": "reference-codex", "profileHash": "reference-v2"}],
            updated_suites,
        )

        self.assertNotEqual(original, replacement)
        self.assertEqual(replacement, duplicate)
        self.assertEqual("cancelled", self.store.campaign_detail(str(original))["campaign"]["status"])

    def test_task_measurement_aggregates_only_its_attempt(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Measurement", "custom", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)
        self.store.ensure_tasks(run["id"], ["task-one"])
        task = self.store.begin_task(self.store.next_task(run["id"])["id"])
        base = {
            "campaignId": campaign_id, "runId": run["id"], "taskId": task["id"], "attempt": 1,
            "apiPath": "/v1/responses", "statusCode": 200, "usageSource": "response", "completed": True,
        }
        self.store.record_request_metric({**base, "requestId": "one", "promptTokens": 20, "completionTokens": 5, "durationMs": 100})
        self.store.record_request_metric({**base, "requestId": "two", "promptTokens": 10, "completionTokens": 7, "durationMs": 200, "toolCalls": 1})
        self.store.complete_task(task["id"], True, 500)
        self.store.record_task_measurement(task["id"], 1, {
            "wall_duration_ms": 500, "idle_power_w": 30, "gross_energy_wh": 0.1,
            "incremental_energy_wh": 0.07, "peak_power_w": 180, "sample_count": 3,
        })
        with self.store.session() as db:
            measured = db.execute("SELECT * FROM task_measurements WHERE task_id=? AND attempt=1", (task["id"],)).fetchone()
            updated_task = db.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()
            updated_run = db.execute("SELECT * FROM runs WHERE id=?", (run["id"],)).fetchone()
        self.assertEqual(2, measured["response_calls"])
        self.assertEqual(300, measured["active_inference_ms"])
        self.assertEqual("complete", measured["measurement_status"])
        self.assertEqual(30, updated_task["prompt_tokens"])
        self.assertEqual(12, updated_task["completion_tokens"])
        self.assertEqual(42, updated_run["total_tokens"])

    def test_incomplete_reference_measurement_reopens_the_task(self):
        profile = {"name": "reference", "profileHash": "hash-a", "executionMode": "external-openai"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Reference", "agent-system-reference-v1", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)
        self.store.ensure_tasks(run["id"], ["task-one"])
        task = self.store.begin_task(self.store.next_task(run["id"])["id"])
        self.store.complete_task(task["id"], True, 500)

        status = self.store.record_task_measurement(task["id"], 1, {"wall_duration_ms": 500})
        retried = self.store.retry_incomplete_measurement_task(
            task["id"], 1, "request accounting missing"
        )

        self.assertEqual("incomplete", status)
        self.assertTrue(retried)
        with self.store.session() as db:
            updated_task = db.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()
            updated_run = db.execute("SELECT * FROM runs WHERE id=?", (run["id"],)).fetchone()
            campaign = db.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
        self.assertEqual(("queued", 2, None), (updated_task["status"], updated_task["attempt"], updated_task["passed"]))
        self.assertEqual("queued", updated_run["status"])
        self.assertEqual("queued", campaign["status"])

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

    def test_manual_retry_resumes_failed_run_after_partial_completion(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 2}
        campaign_id = self.store.create_campaign("Retry partial run", "custom", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)
        self.store.ensure_tasks(run["id"], ["first", "second"])
        first = self.store.next_task(run["id"])
        self.store.begin_task(first["id"])
        self.store.complete_task(first["id"], True, 10)
        self.store.fail_run(run["id"], "resource lease expired during model activation")

        self.assertEqual(1, self.store.retry_campaign_infrastructure(campaign_id))
        retried_run = self.store.campaign_detail(campaign_id)["runs"][0]
        self.assertEqual("interrupted", retried_run["status"])
        self.assertEqual(1, retried_run["completed_tasks"])
        self.assertEqual("second", self.store.next_task(run["id"])["external_task_id"])

    def test_manual_retry_deduplicates_legacy_attempt_rows(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        campaign_id = self.store.create_campaign("Retry duplicate", "custom", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)
        self.store.ensure_tasks(run["id"], ["task-one"])
        task = self.store.next_task(run["id"])
        self.store.begin_task(task["id"])
        self.store.retry_infrastructure_task(task["id"], "retry")
        retried = self.store.begin_task(task["id"])
        self.store.complete_task(retried["id"], False, 10, "infrastructure_failure", "transport failed")
        with self.store.session() as db:
            db.execute(
                "INSERT INTO tasks(id,run_id,external_task_id,attempt,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                ("legacy-duplicate", run["id"], "task-one", 1, "queued", now(), now()),
            )

        self.assertEqual(1, self.store.retry_campaign_infrastructure(campaign_id))
        with self.store.session() as db:
            rows = db.execute("SELECT attempt,status FROM tasks WHERE run_id=?", (run["id"],)).fetchall()
        self.assertEqual([(3, "queued")], [(row["attempt"], row["status"]) for row in rows])

    def test_ensure_tasks_does_not_reinsert_an_advanced_attempt(self):
        profile = {"name": "model-a", "profileHash": "hash-a"}
        suite = {"id": "suite-a", "manifestHash": "suite-hash", "taskCount": 1}
        self.store.create_campaign("No duplicate", "custom", [profile], [suite])
        run = self.store.begin_run(self.store.next_runnable()["id"], None)
        self.store.ensure_tasks(run["id"], ["task-one"])
        task = self.store.next_task(run["id"])
        self.store.begin_task(task["id"])
        self.store.retry_infrastructure_task(task["id"], "retry")

        self.store.ensure_tasks(run["id"], ["task-one"])
        with self.store.session() as db:
            rows = db.execute("SELECT attempt FROM tasks WHERE run_id=?", (run["id"],)).fetchall()
        self.assertEqual([2], [row["attempt"] for row in rows])

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
