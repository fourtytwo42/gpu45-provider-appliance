from __future__ import annotations

from PIL import Image, ImageOps


# Wan's reference TI2V-5B negative prompt. Keeping the original language avoids
# weakening a prompt tuned with the model's multilingual text encoder.
REFERENCE_NEGATIVE_PROMPT = (
    "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，"
    "最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，"
    "画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，"
    "杂乱的背景，三条腿，背景人很多，倒着走，watermark，logo"
)

REFERENCE_SIZE = "1280*704"
REFERENCE_STEPS = 50
REFERENCE_CFG_SCALE = 5.0
REFERENCE_SIGMA_SHIFT = 5.0
REFERENCE_TILE_SIZE = (30, 52)
REFERENCE_TILE_STRIDE = (15, 26)


def prepare_input_image(image: Image.Image, width: int, height: int) -> Image.Image:
    """Crop and resize an input image to the requested frame without black bars."""
    return ImageOps.fit(
        image.convert("RGB"),
        (width, height),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
