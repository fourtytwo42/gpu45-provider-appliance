from __future__ import annotations

from PIL import Image, ImageOps


def prepare_input_image(image: Image.Image, width: int, height: int) -> Image.Image:
    """Crop and resize an input image to the requested frame without black bars."""
    return ImageOps.fit(
        image.convert("RGB"),
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
