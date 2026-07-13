import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("benchmark-qwen36-speculative.py")
SPEC = importlib.util.spec_from_file_location("benchmark_qwen36_speculative", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class OutputIntegrityTests(unittest.TestCase):
    def test_unique_output_is_not_repetitive(self):
        result = MODULE.output_integrity("First sufficiently descriptive line.\nSecond distinct descriptive line.")
        self.assertEqual(result["repeatedLineCount"], 0)
        self.assertEqual(result["repeatedLineRatio"], 0.0)

    def test_repeated_lines_are_counted(self):
        line = "This generated line is long enough to count."
        result = MODULE.output_integrity(f"{line}\n{line}\n{line}")
        self.assertEqual(result["repeatedLineCount"], 2)
        self.assertAlmostEqual(result["repeatedLineRatio"], 2 / 3, places=4)


if __name__ == "__main__":
    unittest.main()
