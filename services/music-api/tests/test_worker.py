import inspect
import os
import tempfile
import unittest
from pathlib import Path

from music_worker import ace_instruction, phase_artifact_ready, run_levo_separation, run_resumable_phase


class WorkerTests(unittest.TestCase):
    def test_ace_task_instructions_are_specific(self):
        self.assertEqual(ace_instruction("extract", {"track_name": "vocals"}), "Extract the vocals track from the audio:")
        self.assertEqual(ace_instruction("lego", {"track_name": "guitar"}), "Generate the guitar track based on the audio context:")
        self.assertEqual(ace_instruction("complete", {"track_classes": "drums, bass"}), "Complete the input track with drums, bass:")
        self.assertEqual(ace_instruction("repaint", {}), "Repaint the mask area based on the given conditions:")

    def test_explicit_instruction_wins(self):
        self.assertEqual(ace_instruction("extract", {"instruction": "Custom"}), "Custom")

    def test_levo_separation_does_not_require_torchcodec(self):
        source = inspect.getsource(run_levo_separation)
        self.assertNotIn("torchaudio.load", source)
        self.assertNotIn("torchaudio.save", source)

    def test_phase_checkpoint_requires_marker_and_nonempty_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "phase.json"
            artifact = root / "artifact.pt"
            marker.write_text("{}", encoding="utf-8")
            artifact.write_bytes(b"x" * 2048)
            self.assertTrue(phase_artifact_ready(marker, artifact))
            artifact.write_bytes(b"short")
            self.assertFalse(phase_artifact_ready(marker, artifact))

    def test_resumable_phase_skips_verified_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "phase.json"
            artifact = root / "artifact.pt"
            progress = root / "progress.json"
            marker.write_text("{}", encoding="utf-8")
            artifact.write_bytes(b"x" * 2048)
            run_resumable_phase(
                ["command-that-must-not-run"], root, progress, 58, "levo-sub-tokens",
                os.environ.copy(), marker, artifact,
            )
            self.assertIn("levo-sub-tokens-restored", progress.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
