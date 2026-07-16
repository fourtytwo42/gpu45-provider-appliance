import os
import sys
import tempfile
import unittest
from pathlib import Path

from agentic_benchmark.harnesses import HarborAdapter, HarnessInterrupted, SweBenchAdapter, TauAdapter, run_interruptible


class HarnessProcessTests(unittest.TestCase):
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

    def test_tau_reliability_expands_trials_without_changing_upstream_ids(self):
        adapter = TauAdapter(self.root / "harnesses", self.root / "artifacts")
        adapter._tasks = ["airline:0", "retail:1"]
        self.assertEqual(
            ["airline:0:trial-1", "airline:0:trial-2", "airline:0:trial-3", "retail:1:trial-1", "retail:1:trial-2", "retail:1:trial-3"],
            adapter.tasks({"trials": 3}),
        )
