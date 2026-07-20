import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from music_api import profiles


class ProfileTests(unittest.TestCase):
    def test_levo_license_hash_is_stable(self):
        self.assertEqual(len(profiles.LEVO_LICENSE_HASH), 64)
        self.assertIn("noncommercial", profiles.LEVO_LICENSE_TEXT.lower())

    def test_profiles_are_capability_driven(self):
        values = profiles.snapshots(False)
        turbo = next(item for item in values if item["id"] == "ace-xl-turbo-4b")
        base = next(item for item in values if item["id"] == "ace-xl-base-4b")
        levo = next(item for item in values if item["id"] == "levo2-large-amd")
        self.assertEqual(turbo["stepOptions"], [8])
        self.assertIn("stems", base["modes"])
        self.assertTrue(levo["noncommercial"])
        self.assertFalse(levo["licenseAccepted"])

    def test_inaccessible_model_directory_is_not_ready(self):
        with patch.object(Path, "is_dir", side_effect=PermissionError):
            self.assertFalse(profiles._contains_weights(Path("/restricted")))


if __name__ == "__main__":
    unittest.main()

