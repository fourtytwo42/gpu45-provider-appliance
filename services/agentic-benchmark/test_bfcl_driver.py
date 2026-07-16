import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from agentic_benchmark.bfcl_driver import configure_lock_root, is_single_case_run, select_entries


class BfclDriverTests(unittest.TestCase):
    def test_selects_exact_case(self):
        entries = [{"id": "case-0"}, {"id": "case-1"}]
        self.assertEqual([{"id": "case-1"}], select_entries(entries, "case-1", 0))

    def test_rejects_unknown_case(self):
        with self.assertRaisesRegex(ValueError, "Unknown BFCL case"):
            select_entries([{"id": "case-0"}], "missing", 0)

    def test_configures_both_bfcl_lock_references(self):
        bfcl = types.ModuleType("bfcl_eval")
        constants = types.ModuleType("bfcl_eval.constants")
        utils = types.ModuleType("bfcl_eval.utils")
        eval_config = types.ModuleType("bfcl_eval.constants.eval_config")
        bfcl.utils = utils
        constants.eval_config = eval_config
        modules = {
            "bfcl_eval": bfcl,
            "bfcl_eval.constants": constants,
            "bfcl_eval.utils": utils,
            "bfcl_eval.constants.eval_config": eval_config,
        }
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, modules):
            path = Path(tmp) / "locks"
            configure_lock_root(path)

        self.assertEqual(path, utils.LOCK_DIR)
        self.assertEqual(path, eval_config.LOCK_DIR)

    def test_exact_case_is_a_single_case_run(self):
        self.assertTrue(is_single_case_run("simple_python_0", 0))
        self.assertTrue(is_single_case_run(None, 1))
        self.assertFalse(is_single_case_run(None, 0))


if __name__ == "__main__":
    unittest.main()
