import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from unittest import mock

from agentic_benchmark.harnesses import (
    BfclAdapter,
    HarborAdapter,
    HarnessInterrupted,
    SweBenchAdapter,
    TauAdapter,
    benchmark_headers,
    bfcl_case_passed,
    container_openai_base_url,
    harbor_agent_config,
    openai_base_url,
    parse_tau_task_id,
    run_interruptible,
    stratified_sample,
    task_attempt_root,
)


class HarnessProcessTests(unittest.TestCase):
    def test_task_artifacts_are_isolated_by_attempt(self):
        first = task_attempt_root(Path("/artifacts"), "campaign", "run", "task", 1)
        second = task_attempt_root(Path("/artifacts"), "campaign", "run", "task", 2)
        self.assertNotEqual(first, second)
        self.assertEqual(Path("/artifacts/campaign/run/task/attempt-2"), second)

    def test_bfcl_case_pass_requires_full_credit(self):
        self.assertTrue(bfcl_case_passed(1.0))
        self.assertFalse(bfcl_case_passed(0.0))

    def test_stratified_sample_is_stable_and_evenly_spaced(self):
        self.assertEqual(["0", "3", "6", "9"], stratified_sample([str(index) for index in range(10)], 4))
        self.assertEqual(["0"], stratified_sample(["0", "1"], 1))
        self.assertEqual(["0", "1"], stratified_sample(["0", "1"], 3))

    def test_benchmark_headers_correlate_attempt(self):
        self.assertEqual(
            {
                "X-GPU45-Benchmark-Token": "secret",
                "X-GPU45-Benchmark-Campaign": "campaign",
                "X-GPU45-Benchmark-Run": "run",
                "X-GPU45-Benchmark-Task": "task",
                "X-GPU45-Benchmark-Attempt": "2",
            },
            benchmark_headers("secret", "campaign", "run", "task", 2),
        )

    def test_reference_endpoint_is_normalized_for_host_and_container_harnesses(self):
        self.assertEqual("http://127.0.0.1:30003/v1", openai_base_url("http://127.0.0.1:30003/"))
        self.assertEqual(
            "http://host.docker.internal:30003/v1",
            container_openai_base_url("http://127.0.0.1:30003"),
        )

    def test_harbor_agent_config_preserves_benchmark_correlation_headers(self):
        headers = benchmark_headers("secret", "campaign", "run", "task", 3)
        self.assertEqual(
            headers,
            harbor_agent_config(headers)["model"]["model_kwargs"]["extra_headers"],
        )

    def test_tau_task_parser_preserves_colons_and_removes_only_trial_suffix(self):
        task_id = "telecom:[mobile_data_issue]roaming_enabled[PERSONA:None]"
        self.assertEqual(
            ("telecom", "[mobile_data_issue]roaming_enabled[PERSONA:None]"),
            parse_tau_task_id(task_id),
        )
        self.assertEqual(
            ("telecom", "[mobile_data_issue]roaming_enabled[PERSONA:None]"),
            parse_tau_task_id(task_id + ":trial-3"),
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_process_captures_output(self):
        log = self.root / "run.log"
        code = run_interruptible(
            [sys.executable, "-c", "print('ok')"], self.root, os.environ.copy(), log, 10,
            lambda: None, lambda: None,
        )
        self.assertEqual(0, code)
        self.assertEqual("ok", log.read_text().strip())

    def test_process_is_terminated_on_control_request(self):
        log = self.root / "run.log"
        with self.assertRaises(HarnessInterrupted):
            run_interruptible(
                [sys.executable, "-c", "import time; time.sleep(30)"], self.root, os.environ.copy(), log, 10,
                lambda: None, lambda: "paused",
            )

    def test_swebench_uses_published_fixed_ids(self):
        harness = self.root / "harnesses"
        ids = harness / "sources" / "sweMini50" / "data" / "subsets" / "size_optimized_sample_ids.json"
        ids.parent.mkdir(parents=True)
        ids.write_text('["django__django-11790", "sympy__sympy-123"]')
        adapter = SweBenchAdapter(harness, self.root / "artifacts")
        self.assertEqual(["django__django-11790", "sympy__sympy-123"], adapter.tasks({}))
        self.assertEqual(["one"], adapter.tasks({"taskIds": ["one"]}))
        self.assertEqual(["django__django-11790", "sympy__sympy-123"], adapter.tasks({"stratifiedTaskCount": 2}))

    @mock.patch("agentic_benchmark.harnesses.run_interruptible", return_value=1)
    def test_swebench_caps_each_agent_turn(self, _run_interruptible):
        adapter = SweBenchAdapter(self.root / "harnesses", self.root / "artifacts", "token")
        adapter.run(
            "campaign", "run", "task", 1, "django__django-11790", "model", 7200,
            lambda: None, lambda: None,
        )

        generated = self.root / "artifacts" / "campaign" / "run" / "task" / "attempt-1" / "gpu45-swebench.yaml"
        generated_text = generated.read_text(encoding="utf-8")
        self.assertIn("  step_limit: 75\n", generated_text)
        self.assertIn("    max_tokens: 4096\n", generated_text)
        self.assertEqual(3600, _run_interruptible.call_args.args[4])

    def test_harbor_discovers_pinned_terminal_bench_tasks(self):
        cache = self.root / "cache"
        for name in ("task-b", "task-a"):
            task = cache / "datasets" / "terminal-bench" / name
            task.mkdir(parents=True)
            (task / "task.toml").write_text('version = "1.0"')
        previous = os.environ.get("GPU45_AGENTIC_CACHE_ROOT")
        os.environ["GPU45_AGENTIC_CACHE_ROOT"] = str(cache)
        try:
            adapter = HarborAdapter(self.root / "harnesses", self.root / "artifacts", "token")
            self.assertEqual(["task-a", "task-b"], adapter.tasks({}))
            self.assertEqual(["one"], adapter.tasks({"taskIds": ["one"]}))
            self.assertEqual(["task-a"], adapter.tasks({"stratifiedTaskCount": 1}))
        finally:
            if previous is None:
                os.environ.pop("GPU45_AGENTIC_CACHE_ROOT", None)
            else:
                os.environ["GPU45_AGENTIC_CACHE_ROOT"] = previous

    def test_harbor_overlay_keeps_agent_install_capabilities(self):
        source = Path(__file__).parent / "agentic_benchmark" / "harnesses.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("cap_drop: [ALL]", text)
        self.assertIn("cap_add: [CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID]", text)
        self.assertIn('glob("*/result.json")', text)
        self.assertIn('f"config_file={agent_config}"', text)

    def test_tau_reliability_expands_trials_without_changing_upstream_ids(self):
        adapter = TauAdapter(self.root / "harnesses", self.root / "artifacts")
        adapter._tasks = ["airline:0", "retail:1"]
        self.assertEqual(
            ["airline:0:trial-1", "airline:0:trial-2", "airline:0:trial-3", "retail:1:trial-1", "retail:1:trial-2", "retail:1:trial-3"],
            adapter.tasks({"trials": 3}),
        )

    def test_tau_stratifies_each_requested_domain(self):
        adapter = TauAdapter(self.root / "harnesses", self.root / "artifacts")
        adapter._tasks = ["airline:0", "airline:1", "airline:2", "retail:0", "retail:1", "retail:2", "telecom:0"]
        self.assertEqual(
            ["airline:0", "airline:2", "retail:0", "retail:2"],
            adapter.tasks({"domains": ["airline", "retail"], "perDomainLimit": 2}),
        )

    @mock.patch("agentic_benchmark.harnesses.subprocess.run")
    def test_bfcl_discovers_individual_cases_and_honors_validation_limit(self, run):
        run.return_value = mock.Mock(stdout='GPU45_TASKS=["simple_python::simple_python_0","simple_python::simple_python_1"]\n')
        adapter = BfclAdapter(self.root / "harnesses", self.root / "artifacts", "token")
        suite = {"categories": ["simple_python"]}

        self.assertEqual(
            ["simple_python::simple_python_0", "simple_python::simple_python_1"],
            adapter.tasks(suite),
        )
        self.assertEqual(["simple_python::simple_python_0"], adapter.tasks({**suite, "validationLimit": 1}))
        self.assertEqual(["simple_python::simple_python_0"], adapter.tasks({**suite, "perCategoryLimit": 1}))
        run.assert_called_once()

    @mock.patch("agentic_benchmark.harnesses.subprocess.run")
    def test_bfcl_discovers_categories_in_separate_processes(self, run):
        run.side_effect = [
            mock.Mock(stdout='GPU45_TASKS=["simple_python::simple_python_0"]\n'),
            mock.Mock(stdout='GPU45_TASKS=["simple_java::simple_java_0"]\n'),
        ]
        adapter = BfclAdapter(self.root / "harnesses", self.root / "artifacts", "token")

        tasks = adapter.tasks({"categories": ["simple_python", "simple_java"]})

        self.assertEqual(["simple_python::simple_python_0", "simple_java::simple_java_0"], tasks)
        self.assertEqual(2, run.call_count)

    @mock.patch("agentic_benchmark.harnesses.subprocess.run")
    def test_bfcl_discovery_reports_subprocess_stderr(self, run):
        run.side_effect = subprocess.CalledProcessError(1, ["python"], stderr="permission denied: fixture")
        adapter = BfclAdapter(self.root / "harnesses", self.root / "artifacts", "token")

        with self.assertRaisesRegex(RuntimeError, "permission denied: fixture"):
            adapter.tasks({"categories": ["simple_python"]})
