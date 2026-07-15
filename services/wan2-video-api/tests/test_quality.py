from __future__ import annotations

import unittest

from PIL import Image

from wan_api.quality import prepare_input_image


class QualitySettingsTests(unittest.TestCase):
    def test_source_image_is_center_cropped_without_letterboxing(self) -> None:
        source = Image.new("RGB", (300, 100), "red")
        output = prepare_input_image(source, 100, 100)

        self.assertEqual(output.size, (100, 100))
        self.assertEqual(output.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(output.getpixel((99, 99)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
