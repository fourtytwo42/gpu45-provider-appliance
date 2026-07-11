from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from gpu45_resource import acquire_lease
from .job_store import JobStore


WAN_ROOT = Path(os.environ.get("WAN2_ROOT", "/opt/wan2.2"))
DATA_DIR = Path(os.environ.get("WAN2_API_DATA", "/models/wan2-video"))
MODEL_DIR = Path(os.environ.get("WAN2_MODEL_DIR", "/models/wan2-video/Wan2.2-TI2V-5B"))
PYTHON = os.environ.get("WAN2_PYTHON", "/opt/wan2-video-venv/bin/python")
HUNYUAN_PYTHON = os.environ.get("HUNYUAN_PYTHON", "/opt/hunyuan-video-venv/bin/python")
HUNYUAN_MODEL_ROOT = Path(os.environ.get("HUNYUAN_MODEL_ROOT", "/models/hunyuan-video-1.5"))
HF_CLI = os.environ.get("WAN2_HF_CLI", str(Path(PYTHON).with_name("huggingface-cli")))
LLM_SERVICE = os.environ.get("WAN2_LLM_SERVICE", "llama-openai.service")
RESTART_LLM = os.environ.get("WAN2_RESTART_LLM_AFTER", "true").lower() in {"1", "true", "yes", "on"}
HF_REPO = os.environ.get("WAN2_HF_REPO", "Wan-AI/Wan2.2-TI2V-5B")
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
    "abstract colors, smoke only, overexposed, blown out highlights, blurry, low quality, "
    "distorted subject, missing subject, text, watermark, painting, cartoon"
)

PROFILES: dict[str, dict[str, Any]] = {
    "wan22-a14b-q3": {
        "id": "wan22-a14b-q3",
        "name": "Wan2.2 A14B Q3 Turbo",
        "description": "Dual-expert A14B profile sized for 32GB with the four-step LightX2V accelerator.",
        "repo": "QuantStack/Wan2.2-T2V-A14B-GGUF",
        "model_dir": DATA_DIR,
        "backend": "hunyuan-comfy",
        "modes": ["t2v"],
        "sizes": ["832*480", "480*832"],
        "durations": [2, 3, 4, 5],
        "step_counts": [4],
        "default_steps": 4,
        "default_fps": 12,
        "expected_vram_gb": 26,
        "required_files": [
            "Wan2.2-T2V-A14B-GGUF/HighNoise/Wan2.2-T2V-A14B-HighNoise-Q3_K_M.gguf",
            "Wan2.2-T2V-A14B-GGUF/LowNoise/Wan2.2-T2V-A14B-LowNoise-Q3_K_M.gguf",
            "comfy-assets/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            "comfy-assets/split_files/vae/wan_2.1_vae.safetensors",
            "comfy-assets/split_files/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
            "comfy-assets/split_files/loras/wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
        ],
        "index_file": None,
        "ready_detail": "Wan2.2 A14B Q3 Turbo",
        "enabled": False,
        "availability_reason": "Validation failed: dual-expert switching exhausted 32GB system RAM and entered swap.",
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
    "wan22-ti2v-5b": {
        "id": "wan22-ti2v-5b",
        "name": "Wan2.2 TI2V 5B",
        "description": "Validated text-to-video and image-to-video profile for this 32GB AMD GPU.",
        "repo": "Wan-AI/Wan2.2-TI2V-5B",
        "model_dir": MODEL_DIR,
        "required_files": [
            "Wan2.2_VAE.pth",
            "models_t5_umt5-xxl-enc-bf16.pth",
            "google/umt5-xxl/tokenizer.json",
        ],
        "index_file": "diffusion_pytorch_model.safetensors.index.json",
        "ready_detail": "Wan2.2 TI2V-5B",
        "modes": ["t2v", "i2v"],
        "sizes": ["832*480", "480*832", "1280*704", "704*1280"],
        "durations": [2, 3, 4, 5],
        "step_counts": [20, 30, 40, 50],
        "default_steps": 30,
        "default_fps": OUTPUT_FPS,
        "expected_vram_gb": 28,
        "known_limitations": [
            "The base TI2V model is not distilled; 12 steps and below produce visibly degraded results.",
            "Text-to-video is less compositionally reliable than image-to-video.",
        ],
    },
    "wan21-t2v-13b": {
        "id": "wan21-t2v-13b",
        "name": "Wan2.1 T2V 1.3B",
        "description": "Experimental fallback. Verified generation works, but prompt adherence is weaker than the 5B profile.",
        "repo": "Wan-AI/Wan2.1-T2V-1.3B",
        "model_dir": DATA_DIR / "Wan2.1-T2V-1.3B",
        "required_files": [
            "Wan2.1_VAE.pth",
            "models_t5_umt5-xxl-enc-bf16.pth",
            "diffusion_pytorch_model.safetensors",
            "google/umt5-xxl/tokenizer.json",
        ],
        "index_file": None,
        "ready_detail": "Wan2.1 T2V-1.3B",
        "sizes": ["832*480", "480*832", "1280*704", "704*1280"],
    },
}


class CreateJobBody(BaseModel):
    prompt: str = Field(..., min_length=1)
    profile: str = "wan22-ti2v-5b"
    negative_prompt: str | None = None
    size: str = "832*480"
    steps: int = Field(default=30, ge=1, le=50)
    duration_seconds: int = Field(default=2, ge=1, le=15)
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
    try:
        return PROFILES[profile_id]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Unsupported Wan profile: {profile_id}.")


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
    return profile_ready(PROFILES["wan22-ti2v-5b"])


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
        "backend": profile.get("backend", "wan-diffsynth"),
        "modes": profile.get("modes", ["t2v"]),
        "sizes": profile.get("sizes", sorted(SUPPORTED_SIZES)),
        "durations": profile.get("durations", list(range(2, 16))),
        "step_counts": profile.get("step_counts", list(range(1, 25))),
        "default_steps": profile.get("default_steps", 8),
        "default_fps": profile.get("default_fps", OUTPUT_FPS),
        "expected_vram_gb": profile.get("expected_vram_gb"),
        "known_limitations": profile.get("known_limitations", []),
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


def terminate_job_processes(job_id: str) -> list[int]:
    terminated: list[int] = []
    try:
        result = subprocess.run(["/usr/bin/pgrep", "-f", f"wan_api.diffsynth_generate.*{job_id}"], check=False, capture_output=True, text=True)
    except OSError:
        return terminated

    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid == os.getpid():
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
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
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


def run_job(job: dict[str, Any]) -> None:
    job_id = job["id"]
    log_path = LOG_DIR / f"{job_id}.log"
    out_prefix = OUTPUT_DIR / job_id
    update_job(job_id, status="running", started_at=now())
    lease = None
    profile = get_profile(job["profile"])
    if profile.get("backend") == "hunyuan-comfy":
        width, height = str(job["size"]).split("*", 1)
        command = [
            HUNYUAN_PYTHON,
            "-m",
            "wan_api.comfy_generate",
            "--job-id",
            job_id,
            "--profile",
            job["profile"],
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
    else:
        command = [
            PYTHON,
            "-m",
            "wan_api.diffsynth_generate",
        "--profile",
        job["profile"],
        "--model-dir",
        job["model_dir"],
        "--output",
        str(out_prefix.with_suffix(".mp4")),
        "--prompt",
        job["prompt"],
        "--size",
        job["size"],
        "--steps",
        str(job["steps"]),
        "--frame-num",
        str(job["frame_num"]),
        "--fps",
            str(job.get("fps", OUTPUT_FPS)),
        ]
        if job.get("negative_prompt"):
            command.extend(["--negative-prompt", job["negative_prompt"]])
        if int(job.get("seed", -1)) >= 0:
            command.extend(["--seed", str(job["seed"])])
        if job.get("source_image_path"):
            command.extend(["--input-image", str(job["source_image_path"])])

    try:
        lease = acquire_lease(job_id, "video", 50, False, "atomic", timeout=1800)
        with log_path.open("w", encoding="utf-8") as log:
            log.write("$ " + " ".join(command) + "\n\n")
            log.flush()
            result = subprocess.run(command, cwd=WAN_ROOT, stdout=log, stderr=subprocess.STDOUT, text=True)
        if result.returncode != 0:
            update_job(job_id, status="failed", completed_at=now(), error=f"generate.py exited with {result.returncode}")
            return
        output = find_output(job_id)
        if not output:
            update_job(job_id, status="failed", completed_at=now(), error="No output video found.")
            return
        update_job(job_id, status="completed", completed_at=now(), output_path=str(output))
    except Exception as exc:
        update_job(job_id, status="failed", completed_at=now(), error=str(exc))
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


app = FastAPI(title="GPU45 Wan2.2 Video API")


@app.get("/health")
def health() -> dict[str, Any]:
    profiles = [public_profile(profile) for profile in PROFILES.values()]
    return {"status": "ok", "model_ready": model_ready(), "model_dir": str(MODEL_DIR), "profiles": profiles}


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
    supported_durations = profile.get("durations")
    if supported_durations and body.duration_seconds not in supported_durations:
        raise HTTPException(status_code=400, detail=f"Unsupported duration for {profile['name']}: {body.duration_seconds}s.")
    fps = int(profile.get("default_fps", OUTPUT_FPS))
    frame_num = duration_to_frame_num(body.duration_seconds) if profile.get("backend") != "hunyuan-comfy" else max(5, ((body.duration_seconds * fps - 1) // 4) * 4 + 1)
    job = {
        "id": str(uuid.uuid4()),
        "profile": profile["id"],
        "profile_name": profile["name"],
        "model_dir": str(profile["model_dir"]),
        "prompt": body.prompt,
        "negative_prompt": (body.negative_prompt or DEFAULT_NEGATIVE_PROMPT).strip(),
        "size": body.size,
        "steps": body.steps,
        "duration_seconds": body.duration_seconds,
        "frame_num": frame_num,
        "fps": fps,
        "seed": body.seed,
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
    profile: str = Form("wan22-ti2v-5b"),
    size: str = Form("832*480"),
    steps: int = Form(30),
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
        prompt=prompt, profile=profile, negative_prompt=negative_prompt,
        size=size, steps=steps, duration_seconds=duration_seconds, seed=seed,
    )
    supported_sizes = set(selected.get("sizes", SUPPORTED_SIZES))
    if body.size not in supported_sizes:
        raise HTTPException(status_code=400, detail=f"Unsupported size for {selected['name']}: {body.size}.")
    if selected.get("step_counts") and body.steps not in selected["step_counts"]:
        raise HTTPException(status_code=400, detail=f"Unsupported step count for {selected['name']}: {body.steps}.")
    if selected.get("durations") and body.duration_seconds not in selected["durations"]:
        raise HTTPException(status_code=400, detail=f"Unsupported duration for {selected['name']}: {body.duration_seconds}s.")
    fps = int(selected.get("default_fps", OUTPUT_FPS))
    job_id = str(uuid.uuid4())
    source_path = UPLOAD_DIR / f"{job_id}{suffix}"
    source_path.write_bytes(payload)
    job = {
        "id": job_id, "profile": selected["id"], "profile_name": selected["name"],
        "model_dir": str(selected["model_dir"]), "mode": "i2v", "source_image_path": str(source_path),
        "prompt": body.prompt, "negative_prompt": (body.negative_prompt or DEFAULT_NEGATIVE_PROMPT).strip(),
        "size": body.size, "steps": body.steps, "duration_seconds": body.duration_seconds,
        "frame_num": duration_to_frame_num(body.duration_seconds), "fps": fps, "seed": body.seed,
        "status": "queued", "created_at": now(), "started_at": None, "completed_at": None,
        "output_path": None, "error": None,
    }
    with lock:
        jobs = load_jobs()
        jobs.append(job)
        save_jobs(jobs)
    ensure_runner()
    return public_job(job)


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    with lock:
        jobs = load_jobs()
        for job in jobs:
            if job["id"] == job_id and job["status"] == "queued":
                job["status"] = "cancelled"
                job["completed_at"] = now()
                save_jobs(jobs)
                return {"ok": True}
            if job["id"] == job_id and job["status"] == "running":
                terminated = terminate_job_processes(job_id)
                job["status"] = "cancelled"
                job["completed_at"] = now()
                job["error"] = "Cancelled by user."
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


@app.post("/model/download", status_code=202)
def download_model(profile: str = "wan22-ti2v-5b") -> dict[str, Any]:
    selected = get_profile(profile)
    if profile_ready(selected):
        return {"ok": True, "message": "Model already downloaded."}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        HF_CLI,
        "download",
        selected["repo"],
        "--local-dir",
        str(selected["model_dir"]),
    ]
    subprocess.Popen(command, cwd=WAN_ROOT, stdout=(LOG_DIR / "model-download.log").open("a"), stderr=subprocess.STDOUT)
    return {"ok": True, "message": "Model download started.", "repo": selected["repo"], "target": str(selected["model_dir"])}


def run() -> None:
    import uvicorn

    host = os.environ.get("WAN2_API_HOST", "0.0.0.0")
    port = int(os.environ.get("WAN2_API_PORT", "8010"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
