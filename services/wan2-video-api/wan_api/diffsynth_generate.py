from __future__ import annotations

import argparse
import time
from pathlib import Path

import torch
from PIL import Image
from diffsynth.pipelines.wan_video import ModelConfig, WanVideoPipeline
from diffsynth.utils.data import save_video


DEFAULT_NEGATIVE_PROMPT = (
    "abstract colors, smoke only, overexposed, blown out highlights, blurry, low quality, "
    "distorted subject, missing subject, text, watermark, painting, cartoon"
)


def parse_size(value: str) -> tuple[int, int]:
    width, height = value.split("*", 1)
    return int(width), int(height)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Wan video through DiffSynth.")
    parser.add_argument("--profile", default="wan22-ti2v-5b")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE_PROMPT)
    parser.add_argument("--size", default="832*480")
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--frame-num", type=int, default=45)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--input-image")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    model_dir = Path(args.model_dir)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    width, height = parse_size(args.size)

    vram_config = {
        "offload_dtype": torch.bfloat16,
        "offload_device": "cpu",
        "onload_dtype": torch.bfloat16,
        "onload_device": "cpu",
        "preparing_dtype": torch.bfloat16,
        "preparing_device": "cuda",
        "computation_dtype": torch.bfloat16,
        "computation_device": "cuda",
    }

    started = time.time()
    print(f"loading DiffSynth {args.profile} pipeline", flush=True)
    if args.profile == "wan21-t2v-13b":
        model_configs = [
            ModelConfig(path=str(model_dir / "diffusion_pytorch_model.safetensors"), **vram_config),
            ModelConfig(path=str(model_dir / "models_t5_umt5-xxl-enc-bf16.pth"), **vram_config),
            ModelConfig(path=str(model_dir / "Wan2.1_VAE.pth"), **vram_config),
        ]
        tokenizer_config = ModelConfig(path=str(model_dir / "google/umt5-xxl"))
    elif args.profile == "wan22-ti2v-5b":
        model_configs = [
            ModelConfig(path=str(model_dir / "models_t5_umt5-xxl-enc-bf16.pth"), **vram_config),
            ModelConfig(path=[
                str(model_dir / "diffusion_pytorch_model-00001-of-00003.safetensors"),
                str(model_dir / "diffusion_pytorch_model-00002-of-00003.safetensors"),
                str(model_dir / "diffusion_pytorch_model-00003-of-00003.safetensors"),
            ]),
            ModelConfig(path=str(model_dir / "Wan2.2_VAE.pth"), **vram_config),
        ]
        tokenizer_config = None
    else:
        raise ValueError(f"Unsupported DiffSynth profile: {args.profile}")

    kwargs = {
        "torch_dtype": torch.bfloat16,
        "device": "cuda",
        "model_configs": model_configs,
        "vram_limit": 28,
    }
    if tokenizer_config is not None:
        kwargs["tokenizer_config"] = tokenizer_config
    pipe = WanVideoPipeline.from_pretrained(**kwargs)
    print(f"pipeline loaded in {time.time() - started:.1f}s", flush=True)

    generate_started = time.time()
    input_image = None
    if args.input_image:
        input_image = Image.open(args.input_image).convert("RGB")
        input_image.thumbnail((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), "black")
        canvas.paste(input_image, ((width - input_image.width) // 2, (height - input_image.height) // 2))
        input_image = canvas

    video = pipe(
        prompt=args.prompt,
        negative_prompt=args.negative_prompt,
        height=height,
        width=width,
        num_frames=args.frame_num,
        num_inference_steps=args.steps,
        cfg_scale=5.0,
        seed=None if args.seed < 0 else args.seed,
        input_image=input_image,
        tiled=True,
        tile_size=(24, 40),
        tile_stride=(12, 20),
        framewise_decoding=True,
    )
    print(f"generated {len(video)} frames in {time.time() - generate_started:.1f}s", flush=True)
    save_video(video, str(output_path), fps=args.fps, quality=5)
    print(f"saved {output_path} in {time.time() - started:.1f}s", flush=True)


if __name__ == "__main__":
    main()
