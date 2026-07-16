from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from gpu45_resource import acquire_lease
from .job_store import JobStore
REFERENCE_SIZE = "512*320"
REFERENCE_STEPS = 8


VIDEO_ROOT = Path(os.environ.get("GPU45_VIDEO_ROOT", "/opt/gpu45-video-api"))
DATA_DIR = Path(os.environ.get("WAN2_API_DATA", "/models/wan2-video"))
HUNYUAN_PYTHON = os.environ.get("HUNYUAN_PYTHON", "/opt/hunyuan-video-venv/bin/python")
HUNYUAN_MODEL_ROOT = Path(os.environ.get("HUNYUAN_MODEL_ROOT", "/models/hunyuan-video-1.5"))
LTX_MODEL_ROOT = Path(os.environ.get("LTX_MODEL_ROOT", "/models/ltx2-eval"))
LLM_SERVICE = os.environ.get("WAN2_LLM_SERVICE", "llama-openai.service")
RESTART_LLM = os.environ.get("WAN2_RESTART_LLM_AFTER", "true").lower() in {"1", "true", "yes", "on"}
JOBS_PATH = DATA_DIR / "jobs.json"
OUTPUT_DIR = DATA_DIR / "outputs"
LOG_DIR = DATA_DIR / "logs"
UPLOAD_DIR = DATA_DIR / "uploads"
_job_store = JobStore(JOBS_PATH)

DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

lock = threading.Lock()
runner_thread: threading.Thread | None = None

SUPPORTED_SIZES = {"832*480", "480*832", "1280*704", "704*1280"}
OUTPUT_FPS = int(os.environ.get("WAN2_OUTPUT_FPS", "24"))
DEFAULT_NEGATIVE_PROMPT = (
    "low quality, blurry, static frame, malformed anatomy, duplicate subjects, "
    "watermark, logo, subtitles, text artifacts"
)

PROFILES: dict[str, dict[str, Any]] = {
    "ltx23-q4": {
        "id": "ltx23-q4",
        "name": "LTX-2.3 Q4",
        "description": "LTX-2.3 Q4 with fast Preview and upscaled Balanced generation presets.",
        "repo": "Lightricks/LTX-2.3 + unsloth/LTX-2.3-GGUF",
        "model_dir": LTX_MODEL_ROOT,
        "backend": "ltx-comfy",
        "modes": ["t2v", "i2v"],
        "sizes": ["512*320", "320*512", "512*288", "288*512", "480*272", "272*480"],
        "durations": list(range(1, 21)),
        "step_counts": [8, 11],
        "default_steps": 8,
        "default_fps": 24,
        "frame_multiple": 8,
        "expected_vram_gb": 19,
        "native_audio": True,
        "features": ["synchronized audio", "text-to-video", "image-to-video", "two-stage latent upscaling"],
        "required_files": [
            "distilled/ltx-2.3-22b-distilled-Q4_K_M.gguf",
            "text_encoders/gemma-3-12b-it-Q2_K.gguf",
            "text_encoders/ltx-2.3_text_projection_bf16.safetensors",
            "vae/LTX23_video_vae_bf16.safetensors",
            "vae/LTX23_audio_vae_bf16.safetensors",
            "latent_upscale_models/ltx-2.3-spatial-upscaler-x2-1.1.safetensors",
        ],
        "index_file": None,
        "ready_detail": "LTX-2.3 Q4",
        "recommended_size": "512*320",
        "recommended_steps": 8,
        "reference_settings": "Preview: 8 distilled steps. Balanced: 8 distilled + 3 refinement steps and 2x latent upscaling.",
        "tested_runtime_seconds": 209,
        "max_tested_duration_seconds": 5,
        "presets": {
            "preview": {
                "label": "Preview",
                "description": "Fast native-resolution generation with synchronized audio.",
                "size": "512*320",
                "steps": 8,
                "duration_seconds": 2,
                "output_scale": 1,
                "max_tested_duration_seconds": 5,
                "modes": ["t2v", "i2v"],
            },
            "balanced": {
                "label": "Balanced",
                "description": "Two-stage generation with 2x latent upscaling and three refinement steps.",
                "size": "512*288",
                "steps": 11,
                "duration_seconds": 2,
                "output_scale": 2,
                "max_tested_duration_seconds": 2,
                "modes": ["t2v", "i2v"],
            },
        },
        "known_limitations": [
            "Preview is hardware-validated through five seconds; longer clips are experimental.",
            "Balanced is hardware-validated through two seconds; longer clips are experimental.",
        ],
    },
    "hunyuan15-t2v-q5": {
        "id": "hunyuan15-t2v-q5",
        "name": "HunyuanVideo 1.5 480p Q5",
        "description": "Quality-focused 480p text-to-video using the CFG-distilled Q5 transformer.",
        "repo": "jayn7/HunyuanVideo-1.5_T2V_480p-GGUF",
        "model_dir": HUNYUAN_MODEL_ROOT,
        "backend": "hunyuan-comfy",
        "modes": ["t2v"],
        "sizes": ["848*480", "480*848"],
        "durations": [2, 3, 4, 5],
        "step_counts": [20, 30, 50],
        "default_steps": 20,
        "default_fps": 12,
        "expected_vram_gb": 22,
        "required_files": [
            "480p_distilled/hunyuanvideo1.5_480p_t2v_cfg_distilled-Q5_K_S.gguf",
            "comfy/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",
            "comfy/split_files/text_encoders/byt5_small_glyphxl_fp16.safetensors",
            "comfy/split_files/vae/hunyuanvideo15_vae_fp16.safetensors",
        ],
        "index_file": None,
        "ready_detail": "HunyuanVideo 1.5 Q5",
        "enabled": False,
        "availability_reason": "Validation failed: ROCm VAE decode exceeded the practical runtime limit.",
    },
}


class CreateJobBody(BaseModel):
    prompt: str = Field(..., min_length=1)
    profile: str = "ltx23-q4"
    preset: str = "preview"
    negative_prompt: str | None = None
    size: str = REFERENCE_SIZE
    steps: int = Field(default=REFERENCE_STEPS, ge=1, le=50)
    duration_seconds: int = Field(default=2, ge=1, le=20)
    seed: int = -1


class ExtendJobBody(BaseModel):
    prompt: str = Field(..., min_length=1)
    negative_prompt: str | None = None
    duration_seconds: int = Field(default=2, ge=1, le=20)
    seed: int = -1


def duration_to_frame_num(seconds: int) -> int:
    target_frames = max(5, seconds * OUTPUT_FPS)
    return round((target_frames - 1) / 4) * 4 + 1


def now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def load_jobs() -> list[dict[str, Any]]:
    return _job_store.load()


def save_jobs(jobs: list[dict[str, Any]]) -> None:
    _job_store.save(jobs)


def get_profile(profile_id: str) -> dict[str, Any]:
    profile_id = {
        "ltx23-q4-preview": "ltx23-q4",
        "ltx23-q4-balanced": "ltx23-q4",
    }.get(profile_id, profile_id)
    try:
        return PROFILES[profile_id]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unsupported video model: {profile_id}.")


def get_preset(profile: dict[str, Any], requested: str, steps: int) -> tuple[str, dict[str, Any]]:
    presets = profile.get("presets") or {}
    preset_id = "balanced" if steps == 11 and "balanced" in presets else requested
    if preset_id not in presets:
        raise HTTPException(status_code=400, detail=f"Unsupported preset for {profile['name']}: {preset_id}.")
    preset = presets[preset_id]
    if steps != int(preset["steps"]):
        raise HTTPException(status_code=400, detail=f"{preset['label']} uses {preset['steps']} steps.")
    return preset_id, preset


def profile_ready(profile: dict[str, Any]) -> bool:
    model_dir = Path(profile["model_dir"])
    if not model_dir.exists():
        return False

    if any(not (model_dir / filename).exists() for filename in profile["required_files"]):
        return False

    if not profile.get("index_file"):
        return True

    index_path = model_dir / str(profile["index_file"])
    if index_path.exists():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        shard_files = set(index.get("weight_map", {}).values())
        return bool(shard_files) and all((model_dir / filename).exists() for filename in shard_files)

    return any(model_dir.glob("*.safetensors"))


def model_ready() -> bool:
    return profile_ready(PROFILES["ltx23-q4"])


def public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    model_dir = Path(profile["model_dir"])
    return {
        "id": profile["id"],
        "name": profile["name"],
        "description": profile["description"],
        "repo": profile["repo"],
        "model_dir": str(model_dir),
        "ready": profile_ready(profile) and profile.get("enabled", True),
        "assets_ready": profile_ready(profile),
        "availability_reason": profile.get("availability_reason"),
        "backend": profile.get("backend", "comfy"),
        "modes": profile.get("modes", ["t2v"]),
        "sizes": profile.get("sizes", sorted(SUPPORTED_SIZES)),
        "durations": profile.get("durations", list(range(2, 16))),
        "step_counts": profile.get("step_counts", list(range(1, 25))),
        "default_steps": profile.get("default_steps", 8),
        "default_fps": profile.get("default_fps", OUTPUT_FPS),
        "expected_vram_gb": profile.get("expected_vram_gb"),
        "solver": profile.get("solver"),
        "recommended_size": profile.get("recommended_size"),
        "recommended_steps": profile.get("recommended_steps"),
        "reference_settings": profile.get("reference_settings"),
        "known_limitations": profile.get("known_limitations", []),
        "native_audio": profile.get("native_audio", False),
        "features": profile.get("features", []),
        "output_scale": profile.get("output_scale", 1),
        "tested_runtime_seconds": profile.get("tested_runtime_seconds"),
        "max_tested_duration_seconds": profile.get("max_tested_duration_seconds"),
        "presets": profile.get("presets", {}),
    }


def systemctl(action: str, service: str) -> None:
    subprocess.run(["/usr/bin/sudo", "-n", "/usr/bin/systemctl", action, service], check=False)


def tail(path: Path, limit: int = 5000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-limit:]


def job_progress(job: dict[str, Any]) -> dict[str, Any]:
    status = job.get("status")
    if status == "completed":
        return {"progress_percent": 100, "progress_label": "Complete", "progress_stage": "completed"}
    if status == "failed":
        return {"progress_percent": 100, "progress_label": "Failed", "progress_stage": "failed"}
    if status == "cancelled":
        return {"progress_percent": 100, "progress_label": "Cancelled", "progress_stage": "cancelled"}
    if status == "queued":
        return {"progress_percent": 0, "progress_label": "Queued", "progress_stage": "queued"}

    log_text = tail(LOG_DIR / f"{job['id']}.log", 12000)
    if not log_text:
        return {"progress_percent": 2, "progress_label": "Starting", "progress_stage": "starting"}

    if "Saving video:" in log_text:
        save_matches = re.findall(r"Saving video:\s+(\d+)%", log_text)
        save_percent = int(save_matches[-1]) if save_matches else 0
        percent = min(99, 90 + round(save_percent * 0.09))
        return {"progress_percent": percent, "progress_label": f"Saving video {save_percent}%", "progress_stage": "saving"}

    stages = re.findall(r"stage=([a-z_]+)(?:\s+elapsed=([0-9.]+)s)?", log_text)
    if stages:
        stage, _elapsed = stages[-1]
        stage_progress = {
            "submitted": (4, "Submitting workflow"),
            "queued": (6, "Waiting for GPU backend"),
            "loading": (10, "Loading Hunyuan models"),
            "denoising": (20, "Denoising video"),
            "decoding": (88, "Decoding frames"),
            "completed": (100, "Complete"),
        }
        percent, label = stage_progress.get(stage, (5, stage.replace("_", " ").title()))
        return {"progress_percent": percent, "progress_label": label, "progress_stage": stage}

    generated_match = re.search(r"generated\s+\d+\s+frames", log_text)
    if generated_match:
        return {"progress_percent": 90, "progress_label": "Encoding output", "progress_stage": "encoding"}

    decode_matches = re.findall(r"VAE decoding:\s+(\d+)%\|.*?\|\s*(\d+)/(\d+)\s*\[", log_text)
    if decode_matches:
        _raw_percent, step, total = decode_matches[-1]
        step_int = int(step)
        total_int = max(1, int(total))
        percent = min(98, 90 + round((step_int / total_int) * 8))
        return {
            "progress_percent": percent,
            "progress_label": f"Decoding frame tiles {step_int}/{total_int}",
            "progress_stage": "decoding",
        }

    ltx_decode_tiles = len(re.findall(r"Processing VAE decode tile at row", log_text))
    if ltx_decode_tiles:
        tile = min(4, ltx_decode_tiles)
        return {
            "progress_percent": min(98, 88 + tile * 2),
            "progress_label": f"Decoding video tile {tile}/4",
            "progress_stage": "decoding",
        }

    step_matches = re.findall(r"(\d+)%\|.*?\|\s*(\d+)/(\d+)\s*\[", log_text)
    if step_matches:
        raw_percent, step, total = step_matches[-1]
        step_int = int(step)
        total_int = max(1, int(total))
        percent = min(89, max(5, round((step_int / total_int) * 90)))
        return {
            "progress_percent": percent,
            "progress_label": f"Denoising step {step_int}/{total_int}",
            "progress_stage": "denoising",
        }

    if "pipeline loaded" in log_text:
        return {"progress_percent": 5, "progress_label": "Preparing denoising", "progress_stage": "preparing"}
    if "Loading models from:" in log_text:
        return {"progress_percent": 3, "progress_label": "Loading model", "progress_stage": "loading"}
    return {"progress_percent": 2, "progress_label": "Starting", "progress_stage": "starting"}


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {**job, **job_progress(job)}


def safe_unlink(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
        if root_resolved not in resolved.parents and resolved != root_resolved:
            return False
        if resolved.exists() and resolved.is_file():
            resolved.unlink()
            return True
    except OSError:
        return False
    return False


def delete_job_files(job_id: str, job: dict[str, Any]) -> list[str]:
    deleted: list[str] = []
    paths: list[tuple[Path, Path]] = [(LOG_DIR / f"{job_id}.log", LOG_DIR)]
    for candidate in OUTPUT_DIR.glob(f"{job_id}*"):
        paths.append((candidate, OUTPUT_DIR))
    if job.get("output_path"):
        paths.append((Path(str(job["output_path"])), OUTPUT_DIR))
    if job.get("source_image_path"):
        paths.append((Path(str(job["source_image_path"])), UPLOAD_DIR))

    seen: set[Path] = set()
    for path, root in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if safe_unlink(path, root):
            deleted.append(str(resolved))
    return deleted


def terminate_job_processes(job_id: str, job: dict[str, Any] | None = None) -> list[int]:
    terminated: list[int] = []
    recorded_pid = int((job or {}).get("process_pid") or 0)
    use_process_group = bool((job or {}).get("process_group"))
    if recorded_pid > 0:
        try:
            if use_process_group:
                os.killpg(os.getpgid(recorded_pid), signal.SIGTERM)
            else:
                os.kill(recorded_pid, signal.SIGTERM)
            terminated.append(recorded_pid)
        except (ProcessLookupError, OSError):
            pass
    try:
        result = subprocess.run(["/usr/bin/pgrep", "-f", f"wan_api.comfy_generate.*{job_id}"], check=False, capture_output=True, text=True)
    except OSError:
        return terminated

    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        if pid in terminated:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            terminated.append(pid)
        except ProcessLookupError:
            continue
    if terminated:
        time.sleep(5)
        for pid in terminated:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            try:
                if pid == recorded_pid and use_process_group:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                else:
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                continue
    return terminated


def update_job(job_id: str, **updates: Any) -> None:
    with lock:
        jobs = load_jobs()
        for job in jobs:
            if job["id"] == job_id:
                job.update(updates)
                break
        save_jobs(jobs)


def find_output(job_id: str) -> Path | None:
    candidates = sorted(OUTPUT_DIR.glob(f"{job_id}*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for candidate in candidates:
        if candidate.suffix.lower() in {".mp4", ".mov", ".webm"}:
            return candidate
    return None


def probe_video(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "/usr/bin/ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=nb_frames,width,height:format=duration",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    stream = (payload.get("streams") or [{}])[0]
    return {
        "duration_seconds": float((payload.get("format") or {}).get("duration") or 0),
        "frame_count": int(stream.get("nb_frames") or 0),
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
    }


def extract_last_frame(video_path: Path, image_path: Path) -> None:
    image_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "/usr/bin/ffmpeg", "-y", "-loglevel", "error", "-sseof", "-0.1",
            "-i", str(video_path), "-frames:v", "1", str(image_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def stitch_extension(parent_path: Path, segment_path: Path, output_path: Path) -> None:
    concat_path = output_path.with_suffix(".concat.txt")
    concat_path.write_text(
        f"file '{parent_path.as_posix()}'\nfile '{segment_path.as_posix()}'\n",
        encoding="utf-8",
    )
    try:
        subprocess.run(
            [
                "/usr/bin/ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                "-i", str(concat_path), "-c", "copy", "-movflags", "+faststart", str(output_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        concat_path.unlink(missing_ok=True)


def validate_video_output(job: dict[str, Any], metadata: dict[str, Any]) -> str | None:
    expected_duration = float(job.get("duration_seconds") or 0)
    actual_duration = float(metadata.get("duration_seconds") or 0)
    tolerance = max(0.5, expected_duration * 0.15)
    if expected_duration > 0 and abs(actual_duration - expected_duration) > tolerance:
        return f"Output duration was {actual_duration:.2f}s; expected approximately {expected_duration:.2f}s."
    if int(metadata.get("frame_count") or 0) <= 1:
        return "Output video does not contain enough decoded frames."
    return None


RECOVERABLE_GPU_FAULT_MARKERS = (
    "Memory access fault by GPU node",
    "Faulty UTCL2 client ID: SDMA",
)


def has_recoverable_gpu_transfer_fault(log_path: Path) -> bool:
    try:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(marker in log_text for marker in RECOVERABLE_GPU_FAULT_MARKERS)


def gpu_runtime_recovered() -> bool:
    try:
        result = subprocess.run(
            ["/opt/rocm/bin/rocm-smi", "--showuse", "--showmeminfo", "vram"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "GPU use (%)" in result.stdout


def run_job(job: dict[str, Any]) -> None:
    job_id = job["id"]
    log_path = LOG_DIR / f"{job_id}.log"
    out_prefix = OUTPUT_DIR / job_id
    update_job(job_id, status="running", started_at=now())
    lease = None
    profile = get_profile(job["profile"])
    width, height = str(job["size"]).split("*", 1)
    command = [
        HUNYUAN_PYTHON,
        "-m",
        "wan_api.comfy_generate",
        "--job-id",
        job_id,
        "--profile",
        job["profile"],
        "--preset",
        job.get("preset", "balanced" if job.get("profile") == "ltx23-q4-balanced" else "preview"),
        "--output",
        str(out_prefix.with_suffix(".mp4")),
        "--prompt",
        job["prompt"],
        "--negative-prompt",
        job["negative_prompt"],
        "--width",
        width,
        "--height",
        height,
        "--frames",
        str(job["frame_num"]),
        "--steps",
        str(job["steps"]),
        "--fps",
        str(job.get("fps", profile.get("default_fps", 12))),
        "--seed",
        str(job["seed"] if int(job.get("seed", -1)) >= 0 else int(time.time())),
    ]
    if job.get("source_image_path"):
        command.extend(["--input-image", str(job["source_image_path"])])

    try:
        lease = acquire_lease(job_id, "video", 50, False, "atomic", timeout=1800)
        max_attempts = 2
        return_code = 1
        with log_path.open("w", encoding="utf-8") as log:
            log.write("$ " + " ".join(command) + "\n\n")
            log.flush()
            for attempt in range(1, max_attempts + 1):
                process = subprocess.Popen(
                    command,
                    cwd=VIDEO_ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
                update_job(job_id, process_pid=process.pid, process_group=True, attempt=attempt)
                return_code = process.wait()
                log.flush()
                if return_code == 0:
                    break
                if attempt >= max_attempts or not has_recoverable_gpu_transfer_fault(log_path):
                    break
                log.write("\nstage=recovering_gpu reason=sdma_memory_transfer_fault retry=1/1\n")
                log.flush()
                time.sleep(8)
                if not gpu_runtime_recovered():
                    log.write("stage=gpu_recovery_failed\n")
                    log.flush()
                    break
                log.write("stage=retrying_generation attempt=2/2\n")
                log.flush()
        if return_code != 0:
            error = f"generate.py exited with {return_code}"
            if has_recoverable_gpu_transfer_fault(log_path):
                error = "AMD GPU memory transfer fault while loading the video model; automatic recovery did not complete the job."
            update_job_unless_cancelled(job_id, status="failed", completed_at=now(), error=error, process_pid=None)
            return
        output = find_output(job_id)
        if not output:
            update_job_unless_cancelled(job_id, status="failed", completed_at=now(), error="No output video found.", process_pid=None)
            return
        metadata = probe_video(output)
        expected_segment = float(job.get("extension_duration_seconds") or job.get("duration_seconds") or 0)
        validation_error = validate_video_output({"duration_seconds": expected_segment}, metadata)
        if validation_error:
            update_job_unless_cancelled(job_id, status="failed", completed_at=now(), error=validation_error, process_pid=None)
            return
        continuation_of = job.get("continuation_of")
        if continuation_of:
            parent = next((item for item in load_jobs() if item.get("id") == continuation_of), None)
            parent_path = Path(str((parent or {}).get("output_path") or ""))
            if not parent or not parent_path.is_file():
                update_job_unless_cancelled(job_id, status="failed", completed_at=now(), error="The parent video is no longer available.", process_pid=None)
                return
            combined_output = OUTPUT_DIR / f"{job_id}-extended.mp4"
            stitch_extension(parent_path, output, combined_output)
            output.unlink(missing_ok=True)
            output = combined_output
            metadata = probe_video(output)
            validation_error = validate_video_output(job, metadata)
            if validation_error:
                update_job_unless_cancelled(job_id, status="failed", completed_at=now(), error=f"Stitched extension failed validation: {validation_error}", process_pid=None)
                return
        update_job_unless_cancelled(
            job_id,
            status="completed",
            completed_at=now(),
            output_path=str(output),
            output_duration_seconds=metadata["duration_seconds"],
            output_frame_count=metadata["frame_count"],
            output_width=metadata["width"],
            output_height=metadata["height"],
            process_pid=None,
        )
    except Exception as exc:
        update_job_unless_cancelled(job_id, status="failed", completed_at=now(), error=str(exc), process_pid=None)
    finally:
        if lease is not None:
            lease.release()


def runner() -> None:
    while True:
        with lock:
            queued = [job for job in load_jobs() if job["status"] == "queued"]
        if not queued:
            break
        run_job(queued[0])


def ensure_runner() -> None:
    global runner_thread
    if runner_thread and runner_thread.is_alive():
        return
    runner_thread = threading.Thread(target=runner, daemon=True)
    runner_thread.start()


def recover_pending_jobs() -> int:
    recovered = 0
    with lock:
        jobs = load_jobs()
        for job in jobs:
            if job.get("status") != "running":
                continue
            job.update(
                status="queued",
                started_at=None,
                process_pid=None,
                process_group=None,
                error=None,
                recovery_message="Resumed after the video service restarted.",
            )
            recovered += 1
        if recovered:
            save_jobs(jobs)
    ensure_runner()
    return recovered


@asynccontextmanager
async def lifespan(_app: FastAPI):
    recover_pending_jobs()
    yield


app = FastAPI(title="GPU45 LTX Video API", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    profiles = [public_profile(profile) for profile in PROFILES.values()]
    return {"status": "ok", "model_ready": model_ready(), "model_dir": str(LTX_MODEL_ROOT), "profiles": profiles}


@app.get("/jobs")
def list_jobs() -> list[dict[str, Any]]:
    return [public_job(job) for job in sorted(load_jobs(), key=lambda x: x["created_at"], reverse=True)]


@app.post("/jobs", status_code=202)
def create_job(body: CreateJobBody) -> dict[str, Any]:
    profile = get_profile(body.profile)
    if not profile.get("enabled", True):
        raise HTTPException(status_code=409, detail=profile.get("availability_reason") or "Profile is unavailable.")
    if not profile_ready(profile):
        raise HTTPException(status_code=409, detail=f"{profile['ready_detail']} model is not downloaded yet.")
    supported_sizes = set(profile.get("sizes", SUPPORTED_SIZES))
    if body.size not in supported_sizes:
        raise HTTPException(status_code=400, detail=f"Unsupported size for {profile['name']}: {body.size}.")
    supported_steps = profile.get("step_counts")
    if supported_steps and body.steps not in supported_steps:
        raise HTTPException(status_code=400, detail=f"Unsupported step count for {profile['name']}: {body.steps}.")
    preset_id, preset = get_preset(profile, body.preset, body.steps)
    if "t2v" not in preset.get("modes", ["t2v"]):
        raise HTTPException(status_code=400, detail=f"{preset['label']} does not support text-to-video.")
    supported_durations = profile.get("durations")
    if supported_durations and body.duration_seconds not in supported_durations:
        raise HTTPException(status_code=400, detail=f"Unsupported duration for {profile['name']}: {body.duration_seconds}s.")
    fps = int(profile.get("default_fps", OUTPUT_FPS))
    if profile.get("backend") in {"hunyuan-comfy", "ltx-comfy"}:
        multiple = int(profile.get("frame_multiple", 4))
        frame_num = max(multiple + 1, round((body.duration_seconds * fps - 1) / multiple) * multiple + 1)
    else:
        frame_num = duration_to_frame_num(body.duration_seconds)
    job = {
        "id": str(uuid.uuid4()),
        "profile": profile["id"],
        "profile_name": profile["name"],
        "preset": preset_id,
        "preset_name": preset["label"],
        "model_dir": str(profile["model_dir"]),
        "prompt": body.prompt,
        "negative_prompt": (body.negative_prompt or DEFAULT_NEGATIVE_PROMPT).strip(),
        "size": body.size,
        "steps": body.steps,
        "duration_seconds": body.duration_seconds,
        "frame_num": frame_num,
        "fps": fps,
        "seed": body.seed,
        "solver": profile.get("solver", "euler"),
        "status": "queued",
        "created_at": now(),
        "started_at": None,
        "completed_at": None,
        "output_path": None,
        "error": None,
    }
    with lock:
        jobs = load_jobs()
        jobs.append(job)
        save_jobs(jobs)
    ensure_runner()
    return public_job(job)


@app.post("/jobs/{job_id}/extend", status_code=202)
def extend_job(job_id: str, body: ExtendJobBody) -> dict[str, Any]:
    parent = next((item for item in load_jobs() if item.get("id") == job_id), None)
    if not parent:
        raise HTTPException(status_code=404, detail="Video job not found.")
    if parent.get("status") != "completed" or not parent.get("output_path"):
        raise HTTPException(status_code=409, detail="Only completed videos can be extended.")
    parent_path = Path(str(parent["output_path"]))
    if not parent_path.is_file():
        raise HTTPException(status_code=404, detail="The parent video output is missing.")
    profile = get_profile(str(parent.get("profile") or ""))
    if profile.get("backend") != "ltx-comfy":
        raise HTTPException(status_code=400, detail="Clip extension currently requires LTX-2.3.")
    if body.duration_seconds not in profile.get("durations", []):
        raise HTTPException(status_code=400, detail=f"Unsupported extension duration: {body.duration_seconds}s.")

    child_id = str(uuid.uuid4())
    source_path = UPLOAD_DIR / f"{child_id}.png"
    try:
        extract_last_frame(parent_path, source_path)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not extract the parent video's final frame: {exc}")

    fps = int(parent.get("fps") or profile.get("default_fps", OUTPUT_FPS))
    multiple = int(profile.get("frame_multiple", 4))
    frame_num = max(multiple + 1, round((body.duration_seconds * fps - 1) / multiple) * multiple + 1)
    parent_duration = float(parent.get("output_duration_seconds") or probe_video(parent_path)["duration_seconds"])
    job = {
        "id": child_id,
        "profile": profile["id"],
        "profile_name": profile["name"],
        "preset": parent.get("preset", "preview"),
        "preset_name": parent.get("preset_name", "Preview"),
        "model_dir": str(profile["model_dir"]),
        "mode": "extend",
        "continuation_of": job_id,
        "root_job_id": parent.get("root_job_id") or job_id,
        "segment_index": int(parent.get("segment_index") or 0) + 1,
        "source_image_path": str(source_path),
        "prompt": body.prompt.strip(),
        "negative_prompt": (body.negative_prompt or parent.get("negative_prompt") or DEFAULT_NEGATIVE_PROMPT).strip(),
        "size": parent["size"],
        "steps": int(parent["steps"]),
        "duration_seconds": round(parent_duration + body.duration_seconds, 3),
        "extension_duration_seconds": body.duration_seconds,
        "frame_num": frame_num,
        "fps": fps,
        "seed": body.seed,
        "solver": parent.get("solver", "euler"),
        "status": "queued",
        "created_at": now(),
        "started_at": None,
        "completed_at": None,
        "output_path": None,
        "error": None,
    }
    with lock:
        jobs = load_jobs()
        jobs.append(job)
        save_jobs(jobs)
    ensure_runner()
    return public_job(job)


@app.post("/jobs/i2v", status_code=202)
async def create_i2v_job(
    file: UploadFile = File(...),
    prompt: str = Form(...),
    negative_prompt: str = Form(DEFAULT_NEGATIVE_PROMPT),
    profile: str = Form("ltx23-q4"),
    preset: str = Form("preview"),
    size: str = Form(REFERENCE_SIZE),
    steps: int = Form(REFERENCE_STEPS),
    duration_seconds: int = Form(2),
    seed: int = Form(-1),
) -> dict[str, Any]:
    selected = get_profile(profile)
    if "i2v" not in selected.get("modes", []):
        raise HTTPException(status_code=400, detail=f"{selected['name']} does not support image-to-video.")
    if not profile_ready(selected) or not selected.get("enabled", True):
        raise HTTPException(status_code=409, detail=selected.get("availability_reason") or "Profile is unavailable.")
    suffix = Path(file.filename or "source.png").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="Source image must be PNG, JPEG, or WebP.")
    payload = await file.read()
    if not payload or len(payload) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Source image must be between 1 byte and 20 MB.")
    body = CreateJobBody(
        prompt=prompt, profile=profile, preset=preset, negative_prompt=negative_prompt,
        size=size, steps=steps, duration_seconds=duration_seconds, seed=seed,
    )
    supported_sizes = set(selected.get("sizes", SUPPORTED_SIZES))
    if body.size not in supported_sizes:
        raise HTTPException(status_code=400, detail=f"Unsupported size for {selected['name']}: {body.size}.")
    if selected.get("step_counts") and body.steps not in selected["step_counts"]:
        raise HTTPException(status_code=400, detail=f"Unsupported step count for {selected['name']}: {body.steps}.")
    preset_id, preset_config = get_preset(selected, body.preset, body.steps)
    if "i2v" not in preset_config.get("modes", []):
        raise HTTPException(status_code=400, detail=f"{preset_config['label']} does not support image-to-video.")
    if selected.get("durations") and body.duration_seconds not in selected["durations"]:
        raise HTTPException(status_code=400, detail=f"Unsupported duration for {selected['name']}: {body.duration_seconds}s.")
    fps = int(selected.get("default_fps", OUTPUT_FPS))
    if selected.get("backend") in {"hunyuan-comfy", "ltx-comfy"}:
        multiple = int(selected.get("frame_multiple", 4))
        frame_num = max(multiple + 1, round((body.duration_seconds * fps - 1) / multiple) * multiple + 1)
    else:
        frame_num = duration_to_frame_num(body.duration_seconds)
    job_id = str(uuid.uuid4())
    source_path = UPLOAD_DIR / f"{job_id}{suffix}"
    source_path.write_bytes(payload)
    job = {
        "id": job_id, "profile": selected["id"], "profile_name": selected["name"],
        "preset": preset_id, "preset_name": preset_config["label"],
        "model_dir": str(selected["model_dir"]), "mode": "i2v", "source_image_path": str(source_path),
        "prompt": body.prompt, "negative_prompt": (body.negative_prompt or DEFAULT_NEGATIVE_PROMPT).strip(),
        "size": body.size, "steps": body.steps, "duration_seconds": body.duration_seconds,
        "frame_num": frame_num, "fps": fps, "seed": body.seed,
        "solver": selected.get("solver", "euler"),
        "status": "queued", "created_at": now(), "started_at": None, "completed_at": None,
        "output_path": None, "error": None,
    }
    with lock:
        jobs = load_jobs()
        jobs.append(job)
        save_jobs(jobs)
    ensure_runner()
    return public_job(job)


def update_job_unless_cancelled(job_id: str, **updates: Any) -> bool:
    with lock:
        jobs = load_jobs()
        for job in jobs:
            if job["id"] != job_id:
                continue
            if job.get("status") == "cancelled":
                return False
            job.update(updates)
            save_jobs(jobs)
            return True
    return False


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    with lock:
        jobs = load_jobs()
        for job in jobs:
            if job["id"] == job_id and job["status"] == "cancelled":
                return {"ok": True, "already_cancelled": True}
            if job["id"] == job_id and job["status"] == "failed" and "exited with -15" in str(job.get("error") or ""):
                job["status"] = "cancelled"
                job["error"] = "Cancelled by user."
                save_jobs(jobs)
                return {"ok": True, "reconciled": True}
            if job["id"] == job_id and job["status"] == "queued":
                job["status"] = "cancelled"
                job["completed_at"] = now()
                save_jobs(jobs)
                return {"ok": True}
            if job["id"] == job_id and job["status"] == "running":
                terminated = terminate_job_processes(job_id, job)
                job["status"] = "cancelled"
                job["completed_at"] = now()
                job["error"] = "Cancelled by user."
                job["process_pid"] = None
                save_jobs(jobs)
                return {"ok": True, "terminated_pids": terminated}
    raise HTTPException(status_code=409, detail="Only queued or running jobs can be cancelled.")


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, Any]:
    with lock:
        jobs = load_jobs()
        job = next((item for item in jobs if item["id"] == job_id), None)
        if not job:
            raise HTTPException(status_code=404, detail="Video job not found.")
        if job.get("status") == "running":
            raise HTTPException(status_code=409, detail="Running jobs cannot be deleted until they finish.")
        if any(item.get("continuation_of") == job_id and item.get("status") in {"queued", "running"} for item in jobs):
            raise HTTPException(status_code=409, detail="This video is being extended and cannot be deleted yet.")

        deleted_files = delete_job_files(job_id, job)
        jobs = [item for item in jobs if item["id"] != job_id]
        save_jobs(jobs)
    return {"ok": True, "deleted_files": deleted_files}


@app.get("/jobs/{job_id}/video")
def get_video(job_id: str) -> FileResponse:
    job = next((item for item in load_jobs() if item["id"] == job_id), None)
    if not job or job.get("status") != "completed" or not job.get("output_path"):
        raise HTTPException(status_code=404, detail="Video output not found.")
    path = Path(job["output_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Video output file missing.")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


def run() -> None:
    import uvicorn

    host = os.environ.get("WAN2_API_HOST", "0.0.0.0")
    port = int(os.environ.get("WAN2_API_PORT", "8010"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
