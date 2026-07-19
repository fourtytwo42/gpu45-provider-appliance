from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentic_benchmark.reference_catalog import load_reference_profiles


class ReferenceCatalogTests(unittest.TestCase):
    def test_loads_and_hashes_loopback_reference_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "profile.json").write_text(
                '{"name":"codex","executionMode":"external-openai","endpointUrl":"http://127.0.0.1:30003/"}',
                encoding="utf-8",
            )

            profiles = load_reference_profiles(root)

        self.assertEqual("http://127.0.0.1:30003", profiles[0]["endpointUrl"])
        self.assertEqual(64, len(profiles[0]["profileHash"]))

    def test_rejects_non_loopback_reference_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "profile.json").write_text(
                '{"name":"codex","executionMode":"external-openai","endpointUrl":"https://example.com"}',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_reference_profiles(root)


if __name__ == "__main__":
    unittest.main()
