import unittest
from unittest.mock import patch

from tts_api import engine_bridge


class EngineBridgeTests(unittest.TestCase):
    def test_resolves_pocket_voice(self):
        with patch.object(engine_bridge, "_pocket_json", return_value=[{"id": "builtin:alba", "name": "Alba", "language": "English"}]):
            voice = engine_bridge.resolve_voice("pocket", "builtin:alba")
        self.assertEqual(voice["name"], "Alba")
        self.assertEqual(voice["engine"], "pocket")

    def test_rejects_unknown_engine(self):
        with self.assertRaises(ValueError):
            engine_bridge.normalize_engine("other")


if __name__ == "__main__":
    unittest.main()
