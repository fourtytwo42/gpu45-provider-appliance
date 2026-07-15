from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_COMFY_URL = "http://127.0.0.1:8188"
LTX_DISTILLED_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"


def request_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI returned HTTP {exc.code}: {detail}") from exc


def t2v_workflow(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": args.model}},
        "2": {
            "class_type": "DualCLIPLoader",
            "inputs": {
                "clip_name1": "qwen_2.5_vl_7b_fp8_scaled.safetensors",
                "clip_name2": "byt5_small_glyphxl_fp16.safetensors",
                "type": "hunyuan_video_15",
                "device": "default",
            },
        },
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": args.prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": args.negative_prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": args.shift}},
        "6": {
            "class_type": "CFGGuider",
            "inputs": {"model": ["5", 0], "positive": ["3", 0], "negative": ["4", 0], "cfg": args.cfg},
        },
        "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": args.seed}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {
            "class_type": "BasicScheduler",
            "inputs": {"model": ["5", 0], "scheduler": "simple", "steps": args.steps, "denoise": 1.0},
        },
        "10": {
            "class_type": "EmptyHunyuanVideo15Latent",
            "inputs": {"width": args.width, "height": args.height, "length": args.frames, "batch_size": 1},
        },
        "11": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["7", 0],
                "guider": ["6", 0],
                "sampler": ["8", 0],
                "sigmas": ["9", 0],
                "latent_image": ["10", 0],
            },
        },
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "hunyuanvideo15_vae_fp16.safetensors"}},
        "13": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["12", 0]}},
        "14": {"class_type": "CreateVideo", "inputs": {"images": ["13", 0], "fps": args.fps}},
        "15": {
            "class_type": "SaveVideo",
            "inputs": {"video": ["14", 0], "filename_prefix": f"gpu45/{args.job_id}", "format": "mp4", "codec": "h264"},
        },
    }


def wan22_a14b_workflow(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "Wan2.2-T2V-A14B-HighNoise-Q3_K_M.gguf"}},
        "2": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "Wan2.2-T2V-A14B-LowNoise-Q3_K_M.gguf"}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": args.prompt, "clip": ["3", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": args.negative_prompt, "clip": ["3", 0]}},
        "6": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 5.0}},
        "7": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["2", 0], "shift": 5.0}},
        "8": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["6", 0], "lora_name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors", "strength_model": 1.0}},
        "9": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["7", 0], "lora_name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors", "strength_model": 1.0}},
        "10": {"class_type": "EmptyHunyuanLatentVideo", "inputs": {"width": args.width, "height": args.height, "length": args.frames, "batch_size": 1}},
        "11": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["8", 0], "add_noise": "enable", "noise_seed": args.seed,
                "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["10", 0],
                "start_at_step": 0, "end_at_step": 2, "return_with_leftover_noise": "enable",
            },
        },
        "12": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "model": ["9", 0], "add_noise": "disable", "noise_seed": 0,
                "steps": 4, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["11", 0],
                "start_at_step": 2, "end_at_step": 4, "return_with_leftover_noise": "disable",
            },
        },
        "13": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "14": {"class_type": "VAEDecode", "inputs": {"samples": ["12", 0], "vae": ["13", 0]}},
        "15": {"class_type": "CreateVideo", "inputs": {"images": ["14", 0], "fps": args.fps}},
        "16": {"class_type": "SaveVideo", "inputs": {"video": ["15", 0], "filename_prefix": f"gpu45/{args.job_id}", "format": "mp4", "codec": "h264"}},
    }


def ltx23_workflow(args: argparse.Namespace) -> dict[str, Any]:
    workflow: dict[str, Any] = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": "ltx-2.3-22b-distilled-Q4_K_M.gguf"}},
        "2": {
            "class_type": "DualCLIPLoaderGGUF",
            "inputs": {
                "clip_name1": "gemma-3-12b-it-Q2_K.gguf",
                "clip_name2": "ltx-2.3_text_projection_bf16.safetensors",
                "type": "ltxv",
            },
        },
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": args.prompt, "clip": ["2", 0]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": args.negative_prompt, "clip": ["2", 0]}},
        "5": {
            "class_type": "EmptyLTXVLatentVideo",
            "inputs": {"width": args.width, "height": args.height, "length": args.frames, "batch_size": 1},
        },
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": "LTX23_audio_vae_bf16.safetensors"}},
        "7": {
            "class_type": "LTXVEmptyLatentAudio",
            "inputs": {"frames_number": args.frames, "frame_rate": args.fps, "batch_size": 1, "audio_vae": ["6", 0]},
        },
        "8": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["5", 0], "audio_latent": ["7", 0]}},
        "9": {
            "class_type": "LTXVConditioning",
            "inputs": {"positive": ["3", 0], "negative": ["4", 0], "frame_rate": float(args.fps)},
        },
        "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": args.seed}},
        "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler_ancestral_cfg_pp"}},
        "12": {"class_type": "ManualSigmas", "inputs": {"sigmas": LTX_DISTILLED_SIGMAS}},
        "13": {
            "class_type": "CFGGuider",
            "inputs": {"cfg": 1.0, "model": ["1", 0], "positive": ["9", 0], "negative": ["9", 1]},
        },
        "14": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {"noise": ["10", 0], "guider": ["13", 0], "sampler": ["11", 0], "sigmas": ["12", 0], "latent_image": ["8", 0]},
        },
        "15": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["14", 0]}},
        "16": {"class_type": "VAELoader", "inputs": {"vae_name": "LTX23_video_vae_bf16.safetensors"}},
        "17": {
            "class_type": "LTXVTiledVAEDecode",
            "inputs": {
                "vae": ["16", 0], "latents": ["15", 0], "horizontal_tiles": 2, "vertical_tiles": 2,
                "overlap": 4, "last_frame_fix": False, "working_device": "auto", "working_dtype": "auto",
            },
        },
        "18": {"class_type": "LTXVAudioVAEDecode", "inputs": {"samples": ["15", 1], "audio_vae": ["6", 0]}},
        "19": {"class_type": "CreateVideo", "inputs": {"images": ["17", 0], "fps": float(args.fps), "audio": ["18", 0], "bit_depth": 8}},
        "20": {
            "class_type": "SaveVideo",
            "inputs": {"video": ["19", 0], "filename_prefix": f"gpu45/{args.job_id}", "format": "auto", "codec": "auto"},
        },
    }

    if args.input_image:
        source_name = Path(args.input_image).name
        workflow.update({
            "30": {"class_type": "LoadImage", "inputs": {"image": source_name}},
            "31": {"class_type": "LTXVPreprocess", "inputs": {"image": ["30", 0], "img_compression": 18}},
            "32": {
                "class_type": "LTXVImgToVideoConditionOnly",
                "inputs": {"vae": ["16", 0], "image": ["31", 0], "latent": ["5", 0], "strength": 0.8, "bypass": False},
            },
        })
        workflow["8"]["inputs"]["video_latent"] = ["32", 0]

    if args.profile == "ltx23-q4-balanced":
        workflow.update({
            "21": {"class_type": "LatentUpscaleModelLoader", "inputs": {"model_name": "ltx-2.3-spatial-upscaler-x2-1.1.safetensors"}},
            "22": {"class_type": "LTXVLatentUpsampler", "inputs": {"samples": ["15", 0], "upscale_model": ["21", 0], "vae": ["16", 0]}},
            "23": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["22", 0], "audio_latent": ["15", 1]}},
            "24": {"class_type": "RandomNoise", "inputs": {"noise_seed": args.seed + 1}},
            "25": {"class_type": "ManualSigmas", "inputs": {"sigmas": "0.85, 0.7250, 0.4219, 0.0"}},
            "26": {"class_type": "CFGGuider", "inputs": {"cfg": 1.0, "model": ["1", 0], "positive": ["9", 0], "negative": ["9", 1]}},
            "27": {
                "class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["24", 0], "guider": ["26", 0], "sampler": ["11", 0], "sigmas": ["25", 0], "latent_image": ["23", 0]},
            },
            "28": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["27", 0]}},
        })
        workflow["17"]["inputs"]["latents"] = ["28", 0]
        workflow["18"]["inputs"]["samples"] = ["28", 1]

    return workflow


def comfy_ready(url: str) -> bool:
    try:
        request_json(f"{url}/system_stats")
        return True
    except Exception:
        return False


def attention_flag_for_frames(frames: int) -> str:
    # Long LTX clips exceed 32 GB with PyTorch's full attention allocation.
    return "--use-split-cross-attention" if frames > 121 else "--use-pytorch-cross-attention"


def start_comfy(args: argparse.Namespace) -> subprocess.Popen[str] | None:
    if comfy_ready(args.comfy_url):
        return None
    Path(args.comfy_output_root).mkdir(parents=True, exist_ok=True)
    command = [
        args.comfy_python, str(Path(args.comfy_root) / "main.py"),
        "--listen", "127.0.0.1", "--port", "8188", "--disable-auto-launch",
        "--output-directory", args.comfy_output_root,
        "--disable-smart-memory", "--disable-pinned-memory", "--disable-async-offload",
        "--cache-none", "--reserve-vram", "0.5", attention_flag_for_frames(args.frames),
    ]
    env = {**os.environ, "HSA_OVERRIDE_GFX_VERSION": "10.3.0", "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL": "1"}
    process = subprocess.Popen(command, cwd=args.comfy_root, env=env, stdout=None, stderr=None, text=True)
    deadline = time.time() + 180
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"ComfyUI exited during startup with code {process.returncode}.")
        if comfy_ready(args.comfy_url):
            print(f"stage=comfy_ready pid={process.pid}", flush=True)
            return process
        time.sleep(2)
    process.terminate()
    raise RuntimeError("ComfyUI did not become ready within 180 seconds.")


def find_saved_video(history: dict[str, Any], output_root: Path, expected_prefix: str | None = None) -> Path:
    outputs = history.get("outputs", {})
    for node in outputs.values():
        for collection in ("videos", "animated", "images"):
            items = node.get(collection, [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                filename = item.get("filename")
                if not filename:
                    continue
                subfolder = item.get("subfolder", "")
                candidate = (output_root / subfolder / filename).resolve()
                if output_root.resolve() in candidate.parents and candidate.exists() and candidate.suffix.lower() in {".mp4", ".webm", ".mov"}:
                    return candidate
    if expected_prefix:
        candidates = sorted(output_root.rglob(f"{expected_prefix}_*.mp4"), key=lambda path: path.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
    raise RuntimeError("ComfyUI completed without a video output.")


def run(args: argparse.Namespace) -> None:
    client_id = str(uuid.uuid4())
    started = time.time()
    comfy_process = start_comfy(args)
    copied_input: Path | None = None
    try:
        if args.input_image:
            source = Path(args.input_image)
            copied_input = Path(args.comfy_input_root) / source.name
            copied_input.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != copied_input.resolve():
                shutil.copy2(source, copied_input)

        if args.profile.startswith("ltx23-"):
            workflow = ltx23_workflow(args)
        else:
            workflow = wan22_a14b_workflow(args) if args.profile == "wan22-a14b-q3" else t2v_workflow(args)
        submitted = request_json(f"{args.comfy_url}/prompt", {"prompt": workflow, "client_id": client_id})
        prompt_id = str(submitted["prompt_id"])
        print(f"stage=submitted prompt_id={prompt_id}", flush=True)

        last_label = ""
        while True:
            history = request_json(f"{args.comfy_url}/history/{prompt_id}").get(prompt_id)
            if history:
                status = history.get("status", {})
                if status.get("status_str") == "error" or not status.get("completed", False):
                    messages = status.get("messages", [])
                    raise RuntimeError(f"ComfyUI generation failed: {messages[-1] if messages else status}")
                source = find_saved_video(history, Path(args.comfy_output_root), args.job_id)
                destination = Path(args.output)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                print(f"stage=completed elapsed={time.time() - started:.1f}s output={destination}", flush=True)
                return

            queue = request_json(f"{args.comfy_url}/queue")
            running_ids = {str(item[1]) for item in queue.get("queue_running", []) if len(item) > 1}
            pending_ids = {str(item[1]) for item in queue.get("queue_pending", []) if len(item) > 1}
            label = "denoising" if prompt_id in running_ids else "queued" if prompt_id in pending_ids else "loading"
            if label != last_label:
                print(f"stage={label} elapsed={time.time() - started:.1f}s", flush=True)
                last_label = label
            time.sleep(2)
    finally:
        if copied_input and copied_input.exists() and Path(args.input_image).resolve() != copied_input.resolve():
            copied_input.unlink(missing_ok=True)
        if comfy_process is not None:
            comfy_process.terminate()
            try:
                comfy_process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                comfy_process.kill()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Generate video through the appliance ComfyUI backend.")
    result.add_argument("--job-id", required=True)
    result.add_argument("--output", required=True)
    result.add_argument("--prompt", required=True)
    result.add_argument("--negative-prompt", default="low quality, blurry, artifacts, watermark, distorted anatomy")
    result.add_argument("--model", default="hunyuanvideo1.5_480p_t2v_cfg_distilled-Q5_K_S.gguf")
    result.add_argument("--profile", default="hunyuan15-t2v-q5")
    result.add_argument("--input-image")
    result.add_argument("--width", type=int, default=848)
    result.add_argument("--height", type=int, default=480)
    result.add_argument("--frames", type=int, default=49)
    result.add_argument("--steps", type=int, default=20)
    result.add_argument("--fps", type=int, default=12)
    result.add_argument("--seed", type=int, default=42)
    result.add_argument("--cfg", type=float, default=1.0)
    result.add_argument("--shift", type=float, default=5.0)
    result.add_argument("--comfy-url", default=DEFAULT_COMFY_URL)
    result.add_argument("--comfy-output-root", default="/models/wan2-video/comfy-output")
    result.add_argument("--comfy-input-root", default="/opt/hunyuan-video-1.5/ComfyUI/input")
    result.add_argument("--comfy-root", default="/opt/hunyuan-video-1.5/ComfyUI")
    result.add_argument("--comfy-python", default="/opt/hunyuan-video-venv/bin/python")
    return result


if __name__ == "__main__":
    run(parser().parse_args())
