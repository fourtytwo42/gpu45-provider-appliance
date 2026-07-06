import gc
import json
import os
import random
import shutil
import subprocess
import time
import uuid
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from ctypes import CDLL
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Literal

import torch
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from huggingface_hub import snapshot_download
from pydantic import BaseModel, Field

DATA_DIR = Path(os.environ.get("IMAGE_API_DATA", "/models/image-gen"))
OUTPUT_DIR = DATA_DIR / "outputs"
JOBS_PATH = DATA_DIR / "jobs.json"
MODEL_BASE = Path(os.environ.get("IMAGE_MODEL_BASE", "/models/image-gen/models"))
LLM_SERVICE = os.environ.get("IMAGE_LLM_SERVICE", "llama-openai.service")
RESTART_LLM = os.environ.get("IMAGE_RESTART_LLM", "true").lower() == "true"
GPU_PEER_SERVICES = [service for service in os.environ.get("IMAGE_GPU_PEER_SERVICES", "qwen3-tts-api.service,wan2-video-api.service").replace(",", " ").split() if service]
TTS_RESOURCE_URL = os.environ.get("IMAGE_TTS_RESOURCE_URL", "http://127.0.0.1:8000/resource")
RECOVERY_START_SERVICES = [service for service in os.environ.get("IMAGE_RECOVERY_START_SERVICES", "qwen3-tts-api.service").replace(",", " ").split() if service]
DEVICE = os.environ.get("IMAGE_DEVICE", "cuda")
DTYPE = torch.bfloat16

@asynccontextmanager
async def lifespan(_app: FastAPI):
    now = now_iso()
    try:
        jobs = load_jobs()
        changed = False
        for job in jobs:
            if job.get("status") in {"queued", "running"}:
                job.update(
                    status="failed",
                    progress_label="Interrupted",
                    error="Image service restarted before this job finished.",
                    completed_at=now,
                    updated_at=now,
                )
                changed = True
        if changed:
            save_jobs(jobs)
            print("Recovered interrupted image jobs after service restart.", flush=True)
    except Exception as exc:
        print(f"Failed to recover interrupted image jobs: {exc}", flush=True)
    try:
        start_gpu_peer_services(RECOVERY_START_SERVICES)
    except Exception as exc:
        print(f"Failed to restart image peer services during recovery: {exc}", flush=True)
    try:
        start_llm()
    except Exception as exc:
        print(f"Failed to restart LLM during image API recovery: {exc}", flush=True)
    yield


app = FastAPI(title="GPU45 Image API", lifespan=lifespan)
_jobs_lock = Lock()
_model_lock = Lock()
_pipeline_cache: dict[str, object] = {}
_libc = CDLL("libc.so.6")


PROFILES = {
    "sdxl-turbo": {
        "id": "sdxl-turbo",
        "name": "SDXL Turbo",
        "description": "Fast tested preview model. Coherent output at 512, 768, and 1024 on this appliance.",
        "repo": "stabilityai/sdxl-turbo",
        "pipeline": "auto",
        "default_steps": 4,
        "default_width": 1024,
        "default_height": 1024,
        "guidance_scale": 0.0,
        "tested": True,
        "resolution_options": [
            {"label": "512 x 512", "width": 512, "height": 512},
            {"label": "768 x 768", "width": 768, "height": 768},
            {"label": "1024 x 1024", "width": 1024, "height": 1024},
        ],
        "test_summary": "512: 9.0s / 8.1GB, 768: 7.9s / 12.5GB, 1024: 10.3s / 10.0GB.",
    },
    "sd-turbo": {
        "id": "sd-turbo",
        "name": "SD Turbo",
        "description": "Very fast draft model. Tested stable at 512 and 768.",
        "repo": "stabilityai/sd-turbo",
        "pipeline": "auto",
        "default_steps": 2,
        "default_width": 512,
        "default_height": 512,
        "guidance_scale": 0.0,
        "tested": True,
        "resolution_options": [
            {"label": "512 x 512", "width": 512, "height": 512},
            {"label": "768 x 768", "width": 768, "height": 768},
        ],
        "test_summary": "512: 3.9s / 5.1GB, 768: 6.1s / 8.0GB.",
    },
    "ssd-1b": {
        "id": "ssd-1b",
        "name": "Segmind SSD-1B",
        "description": "Compact SDXL-derived model. Tested stable through 1024; output is softer than SDXL Turbo but usable.",
        "repo": "segmind/SSD-1B",
        "pipeline": "sdxl",
        "default_steps": 20,
        "default_width": 1024,
        "default_height": 1024,
        "guidance_scale": 7.0,
        "tested": True,
        "resolution_options": [
            {"label": "512 x 512", "width": 512, "height": 512},
            {"label": "768 x 768", "width": 768, "height": 768},
            {"label": "1024 x 1024", "width": 1024, "height": 1024},
        ],
        "test_summary": "512: 7.9s / 7.2GB, 768: 12.3s / 10.0GB, 1024: 24.0s / 7.9GB at 4-step smoke settings.",
    },
    "qwen-image-gguf-q3": {
        "id": "qwen-image-gguf-q3",
        "name": "Qwen Image GGUF Q3_K_M",
        "description": "Highest prompt-following path that currently survives on this appliance. Tested safe only at 512; 768 and 1024 crash/OOM the image service.",
        "repo": "city96/Qwen-Image-gguf",
        "pipeline": "qwen-gguf",
        "base_repo": "callgg/qi-decoder",
        "gguf_file": "qwen-image-Q3_K_M.gguf",
        "default_steps": 8,
        "default_width": 512,
        "default_height": 512,
        "guidance_scale": 4.0,
        "max_width": 512,
        "max_height": 512,
        "tested": True,
        "resolution_options": [
            {"label": "512 x 512", "width": 512, "height": 512},
        ],
        "test_summary": "512: 139.1s / 27.0GB. 768 and 1024 are disabled because they restarted the image API.",
    },
}



class CreateJobBody(BaseModel):
    profile: str = "sdxl-turbo"
    prompt: str = Field(..., min_length=1)
    negative_prompt: str | None = None
    width: int = 1024
    height: int = 1024
    steps: int = Field(default=4, ge=1, le=60)
    guidance_scale: float | None = None
    seed: int = -1


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_BASE.mkdir(parents=True, exist_ok=True)
    if not JOBS_PATH.exists():
        JOBS_PATH.write_text("[]", encoding="utf-8")


def load_jobs() -> list[dict]:
    ensure_dirs()
    with _jobs_lock:
        return json.loads(JOBS_PATH.read_text(encoding="utf-8"))


def save_jobs(jobs: list[dict]) -> None:
    ensure_dirs()
    tmp_path = JOBS_PATH.with_suffix(".tmp")
    with _jobs_lock:
        tmp_path.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        tmp_path.replace(JOBS_PATH)


def update_job(job_id: str, **updates) -> dict:
    jobs = load_jobs()
    for job in jobs:
        if job["id"] == job_id:
            job.update(updates)
            save_jobs(jobs)
            return job
    raise KeyError(job_id)


def profile_dir(profile_id: str) -> Path:
    return MODEL_BASE / profile_id


def profile_ready(profile: dict) -> bool:
    path = profile_dir(profile["id"])
    if profile.get("gguf_file"):
        return (path / profile["gguf_file"]).is_file()
    return path.is_dir() and any(path.glob("*.json"))


def profile_snapshot() -> list[dict]:
    items = []
    for profile in PROFILES.values():
        item = dict(profile)
        item["ready"] = profile_ready(profile)
        items.append(item)
    return items


def run_cmd(args: list[str], *, check: bool = True) -> bool:
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if check and result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        command = " ".join(args)
        raise RuntimeError(f"Command failed ({result.returncode}): {command} {stderr}".strip())
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        command = " ".join(args)
        print(f"Command failed ({result.returncode}): {command} {stderr}".strip(), flush=True)
    return result.returncode == 0


def service_is_active(service: str) -> bool:
    return subprocess.run(["systemctl", "is-active", "--quiet", service], check=False).returncode == 0


def systemctl(action: str, service: str, *, check: bool = True) -> bool:
    return run_cmd(["sudo", "systemctl", action, service], check=check)


def stop_llm() -> None:
    systemctl("stop", LLM_SERVICE)


def start_llm() -> None:
    if RESTART_LLM:
        systemctl("start", LLM_SERVICE, check=False)


def post_json(url: str, payload: dict | None = None, *, timeout: int = 10, required: bool = False) -> dict | None:
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except Exception as exc:
        message = f"HTTP POST failed: {url}: {exc}"
        if required:
            raise RuntimeError(message) from exc
        print(message, flush=True)
        return None


def pause_tts_for_gpu(reason: str) -> dict | None:
    if not TTS_RESOURCE_URL:
        return None
    return post_json(f"{TTS_RESOURCE_URL.rstrip('/')}/pause", {"reason": reason}, timeout=20, required=False)


def resume_tts_after_gpu() -> dict | None:
    if not TTS_RESOURCE_URL:
        return None
    return post_json(f"{TTS_RESOURCE_URL.rstrip('/')}/resume", {}, timeout=20, required=False)


def stop_gpu_peer_services(reason: str) -> list[str]:
    stopped: list[str] = []
    for service in GPU_PEER_SERVICES:
        if service == LLM_SERVICE:
            continue
        if service == "qwen3-tts-api.service" and service_is_active(service):
            pause_tts_for_gpu(reason)
        if service_is_active(service):
            systemctl("stop", service)
            stopped.append(service)
    return stopped


def start_gpu_peer_services(services: list[str]) -> None:
    for service in services:
        systemctl("start", service, check=False)
    if "qwen3-tts-api.service" in services:
        deadline = time.time() + 90
        while time.time() < deadline:
            if resume_tts_after_gpu() is not None:
                break
            time.sleep(1)


def gpu_metrics() -> dict:
    try:
        out = subprocess.check_output(
            ["/opt/rocm/bin/rocm-smi", "--showmeminfo", "vram", "--showtemp", "--json"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        data = json.loads(out)
        gpu = next(iter(data.values()))
        used = gpu.get("VRAM Total Used Memory (B)") or gpu.get("vram total used memory (B)") or 0
        junction = gpu.get("Temperature (Sensor junction) (C)") or gpu.get("temperature sensor junction (C)")
        return {
            "vram_mb": round(float(used) / 1024 / 1024),
            "junction_c": float(junction) if junction is not None else None,
        }
    except Exception:
        return {"vram_mb": None, "junction_c": None}


def update_progress(
    job_id: str,
    percent: float,
    label: str,
    *,
    step: int | None = None,
    total_steps: int | None = None,
    started: float | None = None,
) -> None:
    updates = {
        "progress_percent": round(max(0.0, min(100.0, percent)), 1),
        "progress_label": label,
        "progress_step": step,
        "progress_total": total_steps,
        "updated_at": now_iso(),
    }
    if started and percent > 0:
        elapsed = max(0.0, time.time() - started)
        updates["elapsed_seconds"] = round(elapsed, 2)
        if percent < 99:
            updates["eta_seconds"] = round(max(0.0, elapsed * ((100.0 - percent) / percent)), 2)
        else:
            updates["eta_seconds"] = 0
    update_job(job_id, **updates)


def make_step_callback(job_id: str, total_steps: int, started: float):
    total = max(1, int(total_steps))

    def callback(_pipeline, step: int, _timestep, callback_kwargs: dict):
        completed = min(total, int(step) + 1)
        percent = 10.0 + (completed / total) * 85.0
        update_progress(
            job_id,
            percent,
            f"Denoising step {completed}/{total}",
            step=completed,
            total_steps=total,
            started=started,
        )
        return callback_kwargs

    return callback


def download_profile(profile_id: str) -> dict:
    if profile_id not in PROFILES:
        raise KeyError(profile_id)
    profile = PROFILES[profile_id]
    path = profile_dir(profile_id)
    path.mkdir(parents=True, exist_ok=True)
    allow_patterns = [profile["gguf_file"]] if profile.get("gguf_file") else None
    snapshot_download(
        repo_id=profile["repo"],
        local_dir=str(path),
        local_dir_use_symlinks=False,
        allow_patterns=allow_patterns,
    )
    return {"ok": True, "profile": profile_id, "path": str(path)}


def load_pipeline(profile_id: str):
    if profile_id not in PROFILES:
        raise KeyError(profile_id)
    profile = PROFILES[profile_id]
    path = profile_dir(profile_id)
    if not profile_ready(profile):
        download_profile(profile_id)

    with _model_lock:
        if profile_id in _pipeline_cache:
            return _pipeline_cache[profile_id]

        # Keep only one large image model resident.
        for old in list(_pipeline_cache.values()):
            try:
                old.to("cpu")
            except Exception:
                pass
        _pipeline_cache.clear()
        torch.cuda.empty_cache()

        pipeline_type = profile["pipeline"]
        if pipeline_type == "flux":
            from diffusers import FluxPipeline
            pipe = FluxPipeline.from_pretrained(str(path), torch_dtype=DTYPE)
        elif pipeline_type == "sd3":
            from diffusers import StableDiffusion3Pipeline
            pipe = StableDiffusion3Pipeline.from_pretrained(str(path), torch_dtype=DTYPE)
        elif pipeline_type == "qwen":
            from diffusers import QwenImagePipeline
            pipe = QwenImagePipeline.from_pretrained(str(path), torch_dtype=DTYPE)
        elif pipeline_type == "qwen-gguf":
            from diffusers import DiffusionPipeline, GGUFQuantizationConfig, QwenImageTransformer2DModel
            gguf_path = path / profile["gguf_file"]
            transformer = QwenImageTransformer2DModel.from_single_file(
                str(gguf_path),
                quantization_config=GGUFQuantizationConfig(compute_dtype=DTYPE),
                torch_dtype=DTYPE,
                config=profile["base_repo"],
                subfolder="transformer",
            )
            pipe = DiffusionPipeline.from_pretrained(profile["base_repo"], transformer=transformer, torch_dtype=DTYPE)
        elif pipeline_type == "sdxl":
            from diffusers import StableDiffusionXLPipeline
            pipe = StableDiffusionXLPipeline.from_pretrained(str(path), torch_dtype=DTYPE, use_safetensors=True)
        else:
            from diffusers import AutoPipelineForText2Image
            pipe = AutoPipelineForText2Image.from_pretrained(str(path), torch_dtype=DTYPE, variant="fp16")

        if profile.get("sequential_cpu_offload") and hasattr(pipe, "enable_sequential_cpu_offload"):
            pipe.enable_sequential_cpu_offload()
        elif profile.get("cpu_offload") and hasattr(pipe, "enable_model_cpu_offload"):
            pipe.enable_model_cpu_offload()
        else:
            pipe = pipe.to(DEVICE)
        if hasattr(pipe, "enable_attention_slicing"):
            pipe.enable_attention_slicing()
        if hasattr(pipe, "enable_vae_tiling"):
            pipe.enable_vae_tiling()
        _pipeline_cache[profile_id] = pipe
        return pipe


def unload_pipelines() -> None:
    with _model_lock:
        for pipe in list(_pipeline_cache.values()):
            try:
                pipe.to("cpu")
            except Exception:
                pass
        _pipeline_cache.clear()
    gc.collect()
    try:
        _libc.malloc_trim(0)
    except Exception:
        pass
    try:
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
    except Exception:
        pass


def generate_job(job_id: str) -> None:
    started = time.time()
    peak_vram = 0
    peak_temp = None
    stopped_peer_services: list[str] = []
    try:
        job = update_job(job_id, status="running", started_at=now_iso(), progress_percent=0, progress_label="Starting image job", progress_step=0, progress_total=None, eta_seconds=None, elapsed_seconds=0, updated_at=now_iso())
        profile = PROFILES[job["profile"]]
        update_progress(job_id, 2, "Stopping other GPU services", started=started)
        stopped_peer_services = stop_gpu_peer_services(f"Image generation job {job_id}")
        update_progress(job_id, 4, "Stopping LLM to free VRAM", started=started)
        stop_llm()
        try:
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        except Exception:
            pass
        update_progress(job_id, 5, "Loading image model", started=started)
        pipe = load_pipeline(job["profile"])
        update_progress(job_id, 10, "Image model loaded", step=0, total_steps=job["steps"], started=started)
        seed = job["seed"] if job["seed"] >= 0 else random.randint(0, 2**31 - 1)
        generator_device = "cpu" if profile.get("cpu_offload") else DEVICE
        generator = torch.Generator(device=generator_device).manual_seed(seed)
        kwargs = {
            "prompt": job["prompt"],
            "width": job["width"],
            "height": job["height"],
            "num_inference_steps": job["steps"],
            "generator": generator,
        }
        if profile["pipeline"] == "qwen-gguf":
            kwargs["negative_prompt"] = job.get("negative_prompt") or " "
            if job.get("guidance_scale") is not None:
                kwargs["true_cfg_scale"] = job["guidance_scale"]
        else:
            if job.get("negative_prompt") and profile["pipeline"] not in {"flux", "qwen"}:
                kwargs["negative_prompt"] = job["negative_prompt"]
            if job.get("guidance_scale") is not None:
                kwargs["guidance_scale"] = job["guidance_scale"]
        metrics = gpu_metrics()
        if metrics["vram_mb"]:
            peak_vram = max(peak_vram, metrics["vram_mb"])
        if metrics["junction_c"] is not None:
            peak_temp = max(peak_temp or 0, metrics["junction_c"])
        kwargs["callback_on_step_end"] = make_step_callback(job_id, job["steps"], started)
        kwargs["callback_on_step_end_tensor_inputs"] = []
        try:
            image = pipe(**kwargs).images[0]
        except TypeError as exc:
            if "callback_on_step_end" not in str(exc):
                raise
            kwargs.pop("callback_on_step_end", None)
            kwargs.pop("callback_on_step_end_tensor_inputs", None)
            update_progress(job_id, 15, "Running image model without step callbacks", started=started)
            image = pipe(**kwargs).images[0]
        update_progress(job_id, 96, "Saving image", step=job["steps"], total_steps=job["steps"], started=started)
        metrics = gpu_metrics()
        if metrics["vram_mb"]:
            peak_vram = max(peak_vram, metrics["vram_mb"])
        if metrics["junction_c"] is not None:
            peak_temp = max(peak_temp or 0, metrics["junction_c"])
        output_name = f"{profile['id']}-{job_id}.png"
        output_path = OUTPUT_DIR / output_name
        image.save(output_path)
        update_job(
            job_id,
            status="completed",
            completed_at=now_iso(),
            output_path=str(output_path),
            output_name=output_name,
            duration_seconds=round(time.time() - started, 2),
            peak_vram_mb=peak_vram or None,
            peak_junction_c=peak_temp,
            seed=seed,
            progress_percent=100,
            progress_label="Completed",
            progress_step=job["steps"],
            progress_total=job["steps"],
            eta_seconds=0,
            updated_at=now_iso(),
        )
    except Exception as exc:
        update_job(job_id, status="failed", completed_at=now_iso(), duration_seconds=round(time.time() - started, 2), error=str(exc), progress_label="Failed", updated_at=now_iso())
    finally:
        unload_pipelines()
        start_gpu_peer_services(stopped_peer_services)
        start_llm()


@app.get("/")
def root():
    return {"service": "GPU45 Image API", "health": "/health"}


@app.get("/health")
def health():
    return {"status": "ok", "device": DEVICE, "profiles": profile_snapshot()}


@app.get("/jobs")
def list_jobs():
    return sorted(load_jobs(), key=lambda job: job.get("created_at", ""), reverse=True)


@app.post("/models/{profile_id}/download", status_code=202)
def download_model(profile_id: str):
    try:
        return download_profile(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown profile")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/jobs", status_code=202)
def create_job(body: CreateJobBody, background_tasks: BackgroundTasks):
    if body.profile not in PROFILES:
        raise HTTPException(status_code=400, detail=f"Unknown profile: {body.profile}")
    profile = PROFILES[body.profile]
    resolution_options = profile.get("resolution_options") or []
    if resolution_options and not any(int(option["width"]) == body.width and int(option["height"]) == body.height for option in resolution_options):
        allowed = ", ".join(f"{option['width']}x{option['height']}" for option in resolution_options)
        raise HTTPException(
            status_code=400,
            detail=f"{profile['name']} supports only tested sizes on this appliance: {allowed}.",
        )
    max_width = profile.get("max_width")
    max_height = profile.get("max_height")
    if (max_width and body.width > int(max_width)) or (max_height and body.height > int(max_height)):
        raise HTTPException(
            status_code=400,
            detail=f"{profile['name']} is limited to {max_width}x{max_height} on this appliance.",
        )
    job_id = uuid.uuid4().hex[:12]
    guidance = body.guidance_scale
    if guidance is None:
        guidance = float(profile["guidance_scale"])
    elif float(guidance) <= 0 and float(profile["guidance_scale"]) > 0:
        guidance = float(profile["guidance_scale"])
    job = {
        "id": job_id,
        "profile": body.profile,
        "profile_name": profile["name"],
        "prompt": body.prompt,
        "negative_prompt": body.negative_prompt,
        "width": body.width,
        "height": body.height,
        "steps": body.steps,
        "guidance_scale": guidance,
        "seed": body.seed,
        "status": "queued",
        "progress_percent": 0,
        "progress_label": "Queued",
        "progress_step": 0,
        "progress_total": body.steps,
        "eta_seconds": None,
        "elapsed_seconds": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)
    background_tasks.add_task(generate_job, job_id)
    return job


@app.get("/jobs/{job_id}/image")
def get_image(job_id: str):
    job = next((item for item in load_jobs() if item["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_path = job.get("output_path")
    if job.get("status") != "completed" or not output_path or not Path(output_path).is_file():
        raise HTTPException(status_code=409, detail="Image is not ready")
    return FileResponse(output_path, media_type="image/png", filename=job.get("output_name") or f"{job_id}.png", headers={"x-image-name": job.get("output_name") or f"{job_id}.png"})


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    jobs = load_jobs()
    kept = []
    deleted = None
    for job in jobs:
        if job["id"] == job_id:
            deleted = job
        else:
            kept.append(job)
    if deleted is None:
        raise HTTPException(status_code=404, detail="Job not found")
    output_path = deleted.get("output_path")
    if output_path and Path(output_path).is_file():
        Path(output_path).unlink()
    save_jobs(kept)
    return {"ok": True}


def run():
    import uvicorn
    host = os.environ.get("IMAGE_API_HOST", "0.0.0.0")
    port = int(os.environ.get("IMAGE_API_PORT", "8030"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
