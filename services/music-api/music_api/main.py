from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from .profiles import LEVO_LICENSE_HASH, LEVO_LICENSE_TEXT, get_profile, snapshots
from .runner import MusicRunner, remove_job_files
from .store import MusicStore


HOST = os.environ.get("GPU45_MUSIC_HOST", "127.0.0.1")
PORT = int(os.environ.get("GPU45_MUSIC_PORT", "8060"))
DATA_ROOT = Path(os.environ.get("GPU45_MUSIC_DATA_ROOT", "/models/music"))
DB_PATH = Path(os.environ.get("GPU45_MUSIC_DB", "/var/lib/gpu45/music/music.db"))
SERVICE_ROOT = Path(os.environ.get("GPU45_MUSIC_SERVICE_ROOT", "/opt/gpu45-music-api"))
STORE = MusicStore(DB_PATH)
RUNNER = MusicRunner(STORE, DATA_ROOT, SERVICE_ROOT)


def _license_accepted() -> bool:
    return STORE.license_accepted("levo2", LEVO_LICENSE_HASH)


def _public_job(job: dict[str, object]) -> dict[str, object]:
    result = dict(job)
    profile = get_profile(str(job["profile_id"])) or {}
    result["profile_name"] = profile.get("name")
    result["noncommercial"] = bool(profile.get("noncommercial"))
    return result


def _validate_payload(payload: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    profile_id = str(payload.get("profile_id") or payload.get("profileId") or "ace-xl-turbo-4b")
    profile = get_profile(profile_id)
    if not profile:
        raise ValueError("Unknown music profile.")
    profile_state = next(item for item in snapshots(_license_accepted()) if item["id"] == profile_id)
    if not profile_state.get("ready"):
        raise ValueError(str(profile_state.get("availabilityReason") or "Music profile is unavailable."))
    if profile.get("noncommercial") and not _license_accepted():
        raise ValueError("Accept the current LeVo 2 noncommercial license before using this profile.")
    mode = str(payload.get("mode") or "create")
    task_type = str(payload.get("task_type") or payload.get("taskType") or "text2music")
    if mode not in profile["modes"] or task_type not in profile["taskTypes"]:
        raise ValueError("The selected profile does not support this music workflow.")
    duration = float(payload.get("duration") or profile["duration"]["default"])
    if duration < profile["duration"]["min"] or duration > profile["duration"]["max"]:
        raise ValueError(f"Duration must be between {profile['duration']['min']} and {profile['duration']['max']} seconds.")
    caption = str(payload.get("caption") or payload.get("prompt") or "").strip()
    lyrics = str(payload.get("lyrics") or "").strip()
    if task_type == "text2music" and not caption and not lyrics:
        raise ValueError("A prompt or lyrics are required.")
    normalized = dict(payload)
    normalized.update(profile_id=profile_id, mode=mode, task_type=task_type, duration=duration, caption=caption, lyrics=lyrics)
    return profile, normalized


def _normalize_upload(job_id: str, upload: UploadFile, role: str) -> str:
    filename = Path(upload.filename or "audio").name
    if not filename:
        raise ValueError("Uploaded audio needs a filename.")
    input_dir = DATA_ROOT / "jobs" / job_id / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    raw_path = input_dir / f"{role}-{filename}"
    with raw_path.open("wb") as output:
        shutil.copyfileobj(upload.file, output, length=1024 * 1024)
    if raw_path.stat().st_size > 512 * 1024 * 1024:
        raw_path.unlink(missing_ok=True)
        raise ValueError("Audio uploads are limited to 512 MB.")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type", "-of", "json", str(raw_path)],
        capture_output=True,text=True,timeout=30,check=False,
    )
    if probe.returncode != 0 or '"codec_type": "audio"' not in probe.stdout:
        raw_path.unlink(missing_ok=True)
        raise ValueError("The uploaded file does not contain supported audio.")
    normalized_path = input_dir / f"{role}.wav"
    conversion = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(raw_path), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(normalized_path)],
        capture_output=True,text=True,timeout=300,check=False,
    )
    raw_path.unlink(missing_ok=True)
    if conversion.returncode != 0:
        raise ValueError(f"Audio normalization failed: {conversion.stderr.strip()}")
    return str(normalized_path)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    STORE.initialize()
    STORE.recover()
    RUNNER.start()
    yield
    RUNNER.stop()


app = FastAPI(title="GPU45 Music API", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, object]:
    accepted = _license_accepted()
    profiles = snapshots(accepted)
    return {"status": "ok", "database": str(DB_PATH), "profiles": profiles, "readyProfiles": sum(1 for profile in profiles if profile["ready"])}


@app.get("/")
def snapshot(limit: int = 100, offset: int = 0) -> dict[str, object]:
    accepted = _license_accepted()
    return {
        "healthy": True,
        "profiles": snapshots(accepted),
        "jobs": [_public_job(job) for job in STORE.list_jobs(max(1, min(limit, 250)), max(0, offset))],
        "license": {"levo2": {"hash": LEVO_LICENSE_HASH, "text": LEVO_LICENSE_TEXT, "accepted": accepted}},
    }


@app.get("/jobs")
def list_jobs(limit: int = 100, offset: int = 0, status: str | None = None) -> dict[str, object]:
    jobs = STORE.list_jobs(max(1, min(limit, 250)), max(0, offset), status)
    return {"jobs": [_public_job(job) for job in jobs], "offset": offset, "limit": limit}


@app.post("/jobs", status_code=202)
async def create_job(request: Request) -> dict[str, object]:
    content_type = request.headers.get("content-type", "")
    uploads: list[tuple[str, UploadFile]] = []
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        payload = {key: value for key, value in form.multi_items() if not isinstance(value, UploadFile)}
        for key in ("reference_audio", "source_audio"):
            value = form.get(key)
            if isinstance(value, UploadFile) and value.filename:
                uploads.append((key, value))
    else:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "Request body must be an object.")
        payload = body
    job_id: str | None = None
    try:
        _profile, normalized = _validate_payload(payload)
        upload_roles = {role for role, _upload in uploads}
        task_type = str(normalized["task_type"])
        if task_type in {"cover", "repaint", "complete", "lego", "extract", "separate"} and not (
            normalized.get("source_audio") or "source_audio" in upload_roles
        ):
            raise ValueError("The selected workflow requires source audio.")
        if task_type == "reference" and not (normalized.get("reference_audio") or "reference_audio" in upload_roles):
            raise ValueError("Reference generation requires reference audio.")
        job = STORE.create_job(
            str(normalized["profile_id"]),str(normalized["mode"]),str(normalized["task_type"]),normalized,
            status="preparing" if uploads else "queued",
        )
        job_id = str(job["id"])
        for role, upload in uploads:
            normalized[role] = _normalize_upload(job_id, upload, role)
        if uploads:
            with STORE.connect() as db:
                db.execute("UPDATE jobs SET payload_json=?,status='queued',stage='queued',updated_at=datetime('now') WHERE id=?", (json.dumps(normalized), job_id))
            job = STORE.get_job(job_id) or job
        return _public_job(job)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        if job_id:
            STORE.update(job_id,status="failed",stage="failed",progress=100,error=str(exc))
        raise HTTPException(400, str(exc)) from exc


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, object]:
    job = STORE.get_job(job_id)
    if not job:
        raise HTTPException(404, "Music job not found.")
    return _public_job(job)


@app.post("/jobs/{job_id}/action")
async def job_action(job_id: str, request: Request) -> dict[str, object]:
    body = await request.json()
    action = str(body.get("action") or "") if isinstance(body, dict) else ""
    try:
        if action == "cancel":
            job = STORE.request_cancel(job_id)
            RUNNER.cancel(job_id)
        elif action == "retry":
            job = STORE.retry(job_id)
        else:
            raise ValueError("Supported actions are cancel and retry.")
        return {"ok": True, "job": _public_job(job)}
    except KeyError as exc:
        raise HTTPException(404, "Music job not found.") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, object]:
    try:
        job = STORE.delete(job_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not job:
        raise HTTPException(404, "Music job not found.")
    remove_job_files(DATA_ROOT, job)
    return {"ok": True}


@app.get("/jobs/{job_id}/output")
def output(job_id: str, asset: str = "master") -> FileResponse:
    job = STORE.get_job(job_id)
    if not job:
        raise HTTPException(404, "Music job not found.")
    path_value = job.get("assets", {}).get(asset) if isinstance(job.get("assets"), dict) else None
    if not path_value:
        raise HTTPException(404, "Requested music asset is unavailable.")
    path = Path(str(path_value)).resolve()
    allowed = (DATA_ROOT / "jobs" / job_id / "outputs").resolve()
    if not path.is_file() or not path.is_relative_to(allowed):
        raise HTTPException(404, "Requested music asset is unavailable.")
    return FileResponse(path, filename=path.name)


@app.post("/licenses/levo2/accept")
async def accept_levo(request: Request) -> dict[str, object]:
    body = await request.json()
    if not isinstance(body, dict) or body.get("accepted") is not True or body.get("licenseHash") != LEVO_LICENSE_HASH:
        raise HTTPException(400, "Explicit acceptance of the current LeVo 2 license is required.")
    STORE.accept_license("levo2", LEVO_LICENSE_HASH, str(body.get("acceptedBy") or "hendo420"))
    return {"ok": True, "licenseHash": LEVO_LICENSE_HASH}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    jobs = STORE.list_jobs(10000)
    counts: dict[str, int] = {}
    for job in jobs:
        counts[str(job["status"])] = counts.get(str(job["status"]), 0) + 1
    lines = ["# HELP gpu45_music_jobs Music jobs by status", "# TYPE gpu45_music_jobs gauge"]
    lines.extend(f'gpu45_music_jobs{{status="{status}"}} {count}' for status, count in sorted(counts.items()))
    return "\n".join(lines) + "\n"


def serve() -> None:
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
