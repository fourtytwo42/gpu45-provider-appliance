import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Literal

from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from faster_whisper import WhisperModel
from pydantic import BaseModel
from .job_store import JobStore

MODEL_NAMES = ["tiny", "base", "small", "medium", "large-v3", "turbo"]
DATA_DIR = Path(os.environ.get("WHISPER_API_DATA", "/models/whisper"))
UPLOAD_DIR = DATA_DIR / "uploads"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
JOBS_PATH = DATA_DIR / "jobs.json"
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")

_jobs_lock = Lock()
_model_lock = Lock()
_model_cache: dict[str, WhisperModel] = {}
_job_store = JobStore(JOBS_PATH)


class Job(BaseModel):
    id: str
    filename: str
    model: str
    task: Literal["transcribe", "translate"]
    language: str | None = None
    status: Literal["queued", "running", "completed", "failed"]
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    transcript_path: str | None = None
    transcript_name: str | None = None
    duration_seconds: float | None = None
    media_duration_seconds: float | None = None
    processed_seconds: float | None = None
    progress_percent: float = 0.0
    progress_label: str = "Queued"
    eta_seconds: float | None = None
    error: str | None = None


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    jobs = load_jobs()
    changed = False
    for job in jobs:
        if job.get("status") in {"queued", "running"}:
            job.update(status="failed", progress_label="Interrupted", error="Whisper service restarted before this job finished.", completed_at=now_iso())
            changed = True
    if changed:
        save_jobs(jobs)
    yield


app = FastAPI(title="GPU45 Whisper API", lifespan=lifespan)


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)


def load_jobs() -> list[dict]:
    ensure_dirs()
    return _job_store.load()


def save_jobs(jobs: list[dict]) -> None:
    ensure_dirs()
    _job_store.save(jobs)


def update_job(job_id: str, **updates) -> dict:
    jobs = load_jobs()
    for job in jobs:
        if job["id"] == job_id:
            job.update(updates)
            save_jobs(jobs)
            return job
    raise KeyError(job_id)


def get_model(name: str) -> WhisperModel:
    with _model_lock:
        if name not in _model_cache:
            _model_cache[name] = WhisperModel(name, device=DEVICE, compute_type=COMPUTE_TYPE)
        return _model_cache[name]


def timestamp(seconds: float) -> str:
    total_ms = int(seconds * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{ms:03}"


def estimate_eta(elapsed: float, progress_percent: float) -> float | None:
    if progress_percent <= 0 or progress_percent >= 100:
        return 0.0 if progress_percent >= 100 else None
    total_estimate = elapsed / (progress_percent / 100)
    return max(0.0, total_estimate - elapsed)


def write_markdown(job: dict, segments, info) -> Path:
    transcript_name = f"{Path(job['filename']).stem}-{job['id']}.md"
    transcript_path = TRANSCRIPT_DIR / transcript_name
    lines = [
        f"# Transcript: {job['filename']}",
        "",
        f"- Model: `{job['model']}`",
        f"- Task: `{job['task']}`",
        f"- Language: `{getattr(info, 'language', None) or job.get('language') or 'auto'}`",
        f"- Duration: `{round(float(getattr(info, 'duration', 0.0) or 0.0), 2)}s`",
        f"- Created: `{job['created_at']}`",
        "",
        "## Transcript",
        "",
    ]
    for segment in segments:
        text = segment.text.strip()
        if text:
            lines.append(f"**[{timestamp(segment.start)} - {timestamp(segment.end)}]** {text}")
            lines.append("")
    transcript_path.write_text("\n".join(lines), encoding="utf-8")
    return transcript_path


def run_transcription(job_id: str, input_path: str) -> None:
    started = time.time()
    try:
        job = update_job(job_id, status="running", started_at=now_iso(), progress_percent=1.0, progress_label="Loading model", eta_seconds=None)
        model = get_model(job["model"])
        segments_iter, info = model.transcribe(
            input_path,
            task=job["task"],
            language=job.get("language") or None,
            vad_filter=True,
        )
        media_duration = float(getattr(info, "duration", 0.0) or 0.0)
        update_job(
            job_id,
            media_duration_seconds=round(media_duration, 2) if media_duration > 0 else None,
            progress_percent=2.0,
            progress_label="Transcribing",
        )
        segments = []
        last_update = 0.0
        for segment in segments_iter:
            segments.append(segment)
            processed = float(getattr(segment, "end", 0.0) or 0.0)
            if media_duration > 0:
                progress = min(99.0, max(2.0, (processed / media_duration) * 100))
            else:
                progress = min(95.0, 2.0 + len(segments))
            now = time.time()
            if now - last_update >= 2.0 or progress >= 99.0:
                elapsed = now - started
                update_job(
                    job_id,
                    processed_seconds=round(processed, 2),
                    progress_percent=round(progress, 1),
                    progress_label=f"Transcribed {timestamp(processed)}" + (f" / {timestamp(media_duration)}" if media_duration > 0 else ""),
                    eta_seconds=round(estimate_eta(elapsed, progress) or 0.0, 1) if progress > 0 else None,
                )
                last_update = now
        update_job(job_id, progress_percent=99.0, progress_label="Writing transcript", eta_seconds=0.0)
        transcript_path = write_markdown(job, segments, info)
        try:
            Path(input_path).unlink(missing_ok=True)
        except Exception:
            pass
        update_job(
            job_id,
            status="completed",
            completed_at=now_iso(),
            transcript_path=str(transcript_path),
            transcript_name=transcript_path.name,
            duration_seconds=round(time.time() - started, 2),
            processed_seconds=round(media_duration, 2) if media_duration > 0 else None,
            progress_percent=100.0,
            progress_label="Complete",
            eta_seconds=0.0,
            error=None,
        )
    except Exception as exc:
        update_job(job_id, status="failed", completed_at=now_iso(), duration_seconds=round(time.time() - started, 2), progress_percent=100.0, progress_label="Failed", eta_seconds=0.0, error=str(exc))


@app.get("/")
def root():
    return {"service": "GPU45 Whisper API", "health": "/health"}


@app.get("/health")
def health():
    return {"status": "ok", "models": MODEL_NAMES, "device": DEVICE, "compute_type": COMPUTE_TYPE}


@app.get("/jobs")
def list_jobs():
    return sorted(load_jobs(), key=lambda job: job.get("created_at", ""), reverse=True)


@app.post("/jobs", status_code=202)
async def create_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    model: str = Form("small"),
    task: Literal["transcribe", "translate"] = Form("transcribe"),
    language: str | None = Form(None),
):
    if model not in MODEL_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown model: {model}")
    ensure_dirs()
    job_id = uuid.uuid4().hex[:12]
    safe_name = Path(file.filename or "upload").name
    input_path = UPLOAD_DIR / f"{job_id}-{safe_name}"
    with input_path.open("wb") as target:
        shutil.copyfileobj(file.file, target)
    job = Job(
        id=job_id,
        filename=safe_name,
        model=model,
        task=task,
        language=(language or "").strip() or None,
        status="queued",
        created_at=now_iso(),
    ).model_dump()
    jobs = load_jobs()
    jobs.append(job)
    save_jobs(jobs)
    background_tasks.add_task(run_transcription, job_id, str(input_path))
    return job


@app.get("/jobs/{job_id}/transcript")
def get_transcript(job_id: str):
    job = next((item for item in load_jobs() if item["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    transcript_path = job.get("transcript_path")
    if job.get("status") != "completed" or not transcript_path or not Path(transcript_path).is_file():
        raise HTTPException(status_code=409, detail="Transcript is not ready")
    return FileResponse(
        transcript_path,
        media_type="text/markdown",
        filename=job.get("transcript_name") or f"{job_id}.md",
        headers={"x-transcript-name": job.get("transcript_name") or f"{job_id}.md"},
    )


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
    for folder in (UPLOAD_DIR, TRANSCRIPT_DIR):
        for path in folder.glob(f"*{job_id}*"):
            if path.is_file():
                path.unlink()
    save_jobs(kept)
    return {"ok": True}


def run():
    import uvicorn
    host = os.environ.get("WHISPER_API_HOST", "0.0.0.0")
    port = int(os.environ.get("WHISPER_API_PORT", "8020"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
