import unittest

from music_api.runner import remaining_eta


class RunnerTests(unittest.TestCase):
    def test_learned_eta_wins_over_worker_phase_estimate(self):
        self.assertEqual(remaining_eta(152, True, 179, 75), 77)

    def test_worker_eta_is_used_without_history(self):
        self.assertEqual(remaining_eta(180, False, 93, 80), 93)

    def test_fallback_eta_counts_down(self):
        self.assertEqual(remaining_eta(720, False, None, 120), 600)


if __name__ == "__main__":
    unittest.main()
