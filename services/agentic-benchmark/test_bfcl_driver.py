import unittest

from agentic_benchmark.bfcl_driver import select_entries


class BfclDriverTests(unittest.TestCase):
    def test_selects_exact_case(self):
        entries = [{"id": "case-0"}, {"id": "case-1"}]
        self.assertEqual([{"id": "case-1"}], select_entries(entries, "case-1", 0))

    def test_rejects_unknown_case(self):
        with self.assertRaisesRegex(ValueError, "Unknown BFCL case"):
            select_entries([{"id": "case-0"}], "missing", 0)


if __name__ == "__main__":
    unittest.main()
