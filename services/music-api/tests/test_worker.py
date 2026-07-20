import inspect
import unittest

from music_worker import ace_instruction, run_levo_separation


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


if __name__ == "__main__":
    unittest.main()
