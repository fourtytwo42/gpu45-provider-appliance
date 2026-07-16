import os
import tempfile
import unittest
from pathlib import Path

from agentic_benchmark.harnesses import HarnessInterrupted, SweBenchAdapter, run_interruptible


class HarnessProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_process_captures_output(self):
        log = self.root / "run.log"
        code = run_interruptible(
            ["python", "-c", "print('ok')"], self.root, os.environ.copy(), log, 10,
            lambda: None, lambda: None,
        )
        self.assertEqual(0, code)
        self.assertEqual("ok", log.read_text().strip())

    def test_process_is_terminated_on_control_request(self):
        log = self.root / "run.log"
        with self.assertRaises(HarnessInterrupted):
            run_interruptible(
                ["python", "-c", "import time; time.sleep(30)"], self.root, os.environ.copy(), log, 10,
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
