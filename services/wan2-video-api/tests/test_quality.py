from __future__ import annotations

import unittest

from PIL import Image

from wan_api.quality import (
    REFERENCE_CFG_SCALE,
    REFERENCE_NEGATIVE_PROMPT,
    REFERENCE_SIGMA_SHIFT,
    REFERENCE_SIZE,
    REFERENCE_STEPS,
    REFERENCE_TILE_SIZE,
    REFERENCE_TILE_STRIDE,
    prepare_input_image,
)


class QualitySettingsTests(unittest.TestCase):
    def test_reference_settings_match_wan_ti2v_5b(self) -> None:
        self.assertEqual(REFERENCE_SIZE, "1280*704")
        self.assertEqual(REFERENCE_STEPS, 50)
        self.assertEqual(REFERENCE_CFG_SCALE, 5.0)
        self.assertEqual(REFERENCE_SIGMA_SHIFT, 5.0)
        self.assertEqual(REFERENCE_TILE_SIZE, (24, 40))
        self.assertEqual(REFERENCE_TILE_STRIDE, (12, 20))
        self.assertIn("最差质量", REFERENCE_NEGATIVE_PROMPT)

    def test_source_image_is_center_cropped_without_letterboxing(self) -> None:
        source = Image.new("RGB", (300, 100), "red")
        output = prepare_input_image(source, 100, 100)

        self.assertEqual(output.size, (100, 100))
        self.assertEqual(output.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(output.getpixel((99, 99)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
