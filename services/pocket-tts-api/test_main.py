import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import torch
from fastapi.testclient import TestClient

from pocket_tts_api import main


class FakeModel:
    sample_rate = 24000

    def generate_audio(self, _state, _text, max_tokens=50):
        return torch.zeros(2400)


class PocketTtsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.original = (main.JOBS_PATH, main.VOICES_PATH, main.OUTPUT_DIR)
        main.JOBS_PATH = root / "jobs.json"
        main.VOICES_PATH = root / "voices.json"
        main.OUTPUT_DIR = root / "outputs"
        main.OUTPUT_DIR.mkdir()
        main.voice_states.clear()
        self.client = TestClient(main.app)

    def tearDown(self):
        main.JOBS_PATH, main.VOICES_PATH, main.OUTPUT_DIR = self.original
        self.temp.cleanup()

    def test_lists_builtin_multilingual_voices(self):
        voices = self.client.get("/voices").json()
        self.assertGreaterEqual(len(voices), 26)
        self.assertIn("Spanish", {voice["language"] for voice in voices})

    def test_synthesis_job_persists_audio(self):
        with patch.object(main, "get_model", return_value=FakeModel()), patch.object(main, "get_voice_state", return_value={}):
            response = self.client.post("/jobs", json={"text": "Hello from Pocket TTS.", "voice_id": "builtin:alba"})
            self.assertEqual(response.status_code, 202)
            job_id = response.json()["id"]
            for _ in range(50):
                job = next(item for item in self.client.get("/jobs").json() if item["id"] == job_id)
                if job["status"] == "completed":
                    break
                time.sleep(0.02)
            self.assertEqual(job["status"], "completed")
            self.assertEqual(self.client.get(f"/jobs/{job_id}/audio").status_code, 200)

    def test_direct_synthesis_returns_wav_without_job(self):
        with patch.object(main, "get_model", return_value=FakeModel()), patch.object(main, "get_voice_state", return_value={}):
            response = self.client.post("/synthesize", json={"text": "Audiobook chunk.", "voice_id": "builtin:alba"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-type"], "audio/wav")
            self.assertEqual(self.client.get("/jobs").json(), [])


if __name__ == "__main__":
    unittest.main()
