import tempfile
import unittest
from pathlib import Path

from agentic_benchmark.domain import composite_score, efficiency_rows, load_suite_manifests, ranking_rows


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

    def test_efficiency_requires_quality_solve_and_measurement_gates(self):
        report = efficiency_rows([
            {
                "profileName": "fast",
                "qualityScore": 0.70,
                "successes": 10,
                "measurementComplete": True,
                "activeInferenceMs": 1000,
                "totalTokens": 100,
                "incrementalEnergyWh": 10,
                "grossEnergyWh": 12,
            },
            {
                "profileName": "quality",
                "qualityScore": 0.74,
                "successes": 11,
                "measurementComplete": True,
                "activeInferenceMs": 1500,
                "totalTokens": 120,
                "incrementalEnergyWh": 12,
                "grossEnergyWh": 15,
            },
            {
                "profileName": "too-weak",
                "qualityScore": 0.60,
                "successes": 11,
                "measurementComplete": True,
                "activeInferenceMs": 100,
                "totalTokens": 10,
                "incrementalEnergyWh": 1,
                "grossEnergyWh": 2,
            },
        ])
        by_name = {row["profileName"]: row for row in report["rows"]}
        self.assertTrue(by_name["fast"]["eligible"])
        self.assertTrue(by_name["quality"]["eligible"])
        self.assertFalse(by_name["too-weak"]["qualityEligible"])
        self.assertIsNone(by_name["too-weak"]["efficiencyIndex"])

    def test_efficiency_tie_window_requests_confirmation(self):
        report = efficiency_rows([
            {"profileName": "a", "qualityScore": 0.8, "successes": 11, "measurementComplete": True, "activeInferenceMs": 1000, "totalTokens": 100, "incrementalEnergyWh": 10},
            {"profileName": "b", "qualityScore": 0.8, "successes": 11, "measurementComplete": True, "activeInferenceMs": 1010, "totalTokens": 101, "incrementalEnergyWh": 10.1},
        ])
        self.assertTrue(report["tie"])
        self.assertTrue(report["confirmationRecommended"])


if __name__ == "__main__":
    unittest.main()
