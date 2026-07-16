import tempfile
import unittest
from pathlib import Path

from agentic_benchmark.domain import composite_score, load_suite_manifests, ranking_rows


class DomainTests(unittest.TestCase):
    def test_composite_requires_every_common_suite(self):
        self.assertIsNone(composite_score({"bfcl-v4-local": 1.0}))
        score = composite_score({
            "swe-verified-mini50": 0.5,
            "terminal-bench-2": 0.4,
            "bfcl-v4-local": 0.8,
            "tau-text-base": 0.6,
        })
        self.assertEqual(score, 0.545)

    def test_manifest_loader_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = '{"id":"same","requiresDocker":false}'
            (root / "a.json").write_text(payload)
            (root / "b.json").write_text(payload)
            with self.assertRaises(ValueError):
                load_suite_manifests(root)

    def test_ranking_uses_composite_then_swe(self):
        runs = []
        for profile, scores in {
            "model-a": [0.5, 0.5, 0.5, 0.5],
            "model-b": [0.7, 0.5, 0.5, 0.5],
        }.items():
            for suite, score in zip(("swe-verified-mini50", "terminal-bench-2", "bfcl-v4-local", "tau-text-base"), scores):
                runs.append({"profile_name": profile, "suite_id": suite, "track": "controlled", "status": "completed", "score": score})
        self.assertEqual(ranking_rows(runs)[0]["profileName"], "model-b")


if __name__ == "__main__":
    unittest.main()
