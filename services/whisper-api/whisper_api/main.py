import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Literal

from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from faster_whisper import WhisperModel
from pydantic import BaseModel
from gpu45_resource import acquire_lease, activate_profile, resource_state, touch_worker, unload_provider
from .job_store import JobStore
from .outline import (
    OUTLINE_LONG_MODEL,
    OUTLINE_LONG_PROFILE,
    OUTLINE_MODEL,
    OUTLINE_PROFILE,
    OutlineGenerator,
    outline_target,
    render_outline,
)

MODEL_NAMES = ["tiny", "base", "small", "medium", "large-v3", "turbo"]
DATA_DIR = Path(os.environ.get("WHISPER_API_DATA", "/models/whisper"))
UPLOAD_DIR = DATA_DIR / "uploads"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
OUTLINE_DIR = DATA_DIR / "outlines"
JOBS_PATH = DATA_DIR / "jobs.json"
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
GPU_ENABLED = DEVICE.lower() != "cpu"

_jobs_lock = Lock()
_model_lock = Lock()
_outline_lock = Lock()
_active_outline_jobs: set[str] = set()
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
    generate_outline: bool = False
    outline_status: Literal["not_requested", "queued", "running", "completed", "failed"] = "not_requested"
    outline_path: str | None = None
    outline_name: str | None = None
    outline_model: str | None = None
    outline_started_at: str | None = None
    outline_completed_at: str | None = None
    outline_progress_percent: float = 0.0
    outline_progress_label: str | None = None
    outline_eta_seconds: float | None = None
    outline_error: str | None = None


class WorkerHeartbeat:
    def __init__(self, kind: str):
        self.kind = kind
        self.stop_event = Event()
        self.thread = Thread(target=self._run, daemon=True)

    def start(self) -> None:
        try:
            touch_worker(self.kind)
        except Exception:
            pass
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)

    def _run(self) -> None:
        while not self.stop_event.wait(30):
            try:
                touch_worker(self.kind)
            except Exception:
                pass


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    jobs = load_jobs()
    changed = False
    recover_outlines = []
    for job in jobs:
        if job.get("status") in {"queued", "running"}:
            job.update(status="failed", progress_label="Interrupted", error="Whisper service restarted before this job finished.", completed_at=now_iso())
            changed = True
        if job.get("outline_status") in {"queued", "running"} and job.get("transcript_path") and Path(job["transcript_path"]).is_file():
            job.update(
                outline_status="queued",
                outline_progress_label="Recovering outline generation",
                outline_eta_seconds=None,
                outline_error=None,
            )
            recover_outlines.append(job["id"])
            changed = True
    if changed:
        save_jobs(jobs)
    for job_id in recover_outlines:
        Thread(target=run_outline, args=(job_id,), daemon=True).start()
    yield


app = FastAPI(title="GPU45 Whisper API", lifespan=lifespan)


def ensure_dirs() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    OUTLINE_DIR.mkdir(parents=True, exist_ok=True)


def load_jobs() -> list[dict]:
    ensure_dirs()
    return _job_store.load()


def save_jobs(jobs: list[dict]) -> None:
    ensure_dirs()
    _job_store.save(jobs)


def update_job(job_id: str, **updates) -> dict:
    with _jobs_lock:
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
    lease = None
    should_outline = False
    heartbeat = WorkerHeartbeat("whisper")
    heartbeat.start()
    try:
        job = update_job(job_id, status="running", started_at=now_iso(), progress_percent=1.0, progress_label="Waiting for compute", eta_seconds=None)
        if GPU_ENABLED:
            lease = acquire_lease(job_id, "whisper", 70, False, "atomic", timeout=1800)
        update_job(job_id, progress_label="Loading model")
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
        should_outline = bool(job.get("generate_outline"))
    except Exception as exc:
        failure_updates = {
            "status": "failed",
            "completed_at": now_iso(),
            "duration_seconds": round(time.time() - started, 2),
            "progress_percent": 100.0,
            "progress_label": "Failed",
            "eta_seconds": 0.0,
            "error": str(exc),
        }
        if "job" in locals() and job.get("generate_outline"):
            failure_updates.update(
                outline_status="failed",
                outline_progress_percent=100.0,
                outline_progress_label="Transcript failed before outline generation",
                outline_eta_seconds=0.0,
                outline_error="Transcript must complete before an outline can be created.",
            )
        update_job(job_id, **failure_updates)
    finally:
        if lease is not None:
            lease.release()
        heartbeat.stop()
    if should_outline:
        run_outline(job_id)


def run_outline(job_id: str) -> None:
    started = time.time()
    lease = None
    previous_profile = None
    previous_llm_running = False
    outline_profile = OUTLINE_PROFILE
    outline_model = OUTLINE_MODEL
    heartbeat = WorkerHeartbeat("whisper")
    heartbeat.start()
    claimed_outline_slot = False
    try:
        while True:
            with _outline_lock:
                if job_id not in _active_outline_jobs:
                    _active_outline_jobs.add(job_id)
                    claimed_outline_slot = True
                    break
            update_job(
                job_id,
                outline_status="queued",
                outline_progress_percent=0.0,
                outline_progress_label="Waiting for the current outline job to finish",
                outline_eta_seconds=None,
            )
            time.sleep(1)
        job = update_job(
            job_id,
            outline_status="running",
            outline_started_at=now_iso(),
            outline_completed_at=None,
            outline_progress_percent=1.0,
            outline_progress_label="Waiting for outline model",
            outline_eta_seconds=None,
            outline_error=None,
        )
        transcript_path = Path(str(job.get("transcript_path") or ""))
        if not transcript_path.is_file():
            raise RuntimeError("Transcript file is missing")
        markdown = transcript_path.read_text(encoding="utf-8")
        outline_profile, outline_model = outline_target(markdown)

        lease = acquire_lease(f"outline-{job_id}", "llm", 70, False, "restore-profile", timeout=1800)
        state = resource_state()
        provider = state.get("provider") or {}
        previous_profile = provider.get("profileName")
        previous_llm_running = (state.get("services") or {}).get("llm") in {"active", "activating"}
        update_job(job_id, outline_progress_percent=3.0, outline_progress_label="Loading outline model")
        activate_profile(outline_profile)

        generator = OutlineGenerator(model=outline_model)

        def on_progress(step: int, total: int, label: str) -> None:
            progress = 5.0 + ((step / max(1, total)) * 90.0)
            update_job(
                job_id,
                outline_progress_percent=round(progress, 1),
                outline_progress_label=label,
                outline_eta_seconds=round(estimate_eta(time.time() - started, progress) or 0.0, 1),
            )

        content = generator.generate(markdown, job["filename"], on_progress)
        outline_name = f"{Path(job['filename']).stem}-{job_id}-outline.md"
        outline_path = OUTLINE_DIR / outline_name
        temporary = outline_path.with_suffix(".md.tmp")
        temporary.write_text(render_outline(job["filename"], outline_model, content), encoding="utf-8")
        temporary.replace(outline_path)
        update_job(
            job_id,
            generate_outline=True,
            outline_status="completed",
            outline_path=str(outline_path),
            outline_name=outline_name,
            outline_model=outline_model,
            outline_completed_at=now_iso(),
            outline_progress_percent=100.0,
            outline_progress_label="Outline ready",
            outline_eta_seconds=0.0,
            outline_error=None,
        )
    except Exception as exc:
        update_job(
            job_id,
            outline_status="failed",
            outline_completed_at=now_iso(),
            outline_progress_percent=100.0,
            outline_progress_label="Outline failed",
            outline_eta_seconds=0.0,
            outline_error=str(exc),
        )
    finally:
        if lease is not None:
            try:
                if previous_profile and previous_profile != outline_profile:
                    activate_profile(str(previous_profile))
                if not previous_llm_running:
                    unload_provider()
            except Exception:
                pass
            lease.release()
        heartbeat.stop()
        if claimed_outline_slot:
            with _outline_lock:
                _active_outline_jobs.discard(job_id)


@app.get("/")
def root():
    return {"service": "GPU45 Whisper API", "health": "/health"}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "models": MODEL_NAMES,
        "device": DEVICE,
        "compute_type": COMPUTE_TYPE,
        "outline_model": f"Auto: {OUTLINE_MODEL} / {OUTLINE_LONG_MODEL}",
        "outline_profile": OUTLINE_PROFILE,
        "outline_long_profile": OUTLINE_LONG_PROFILE,
    }


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
    generate_outline: bool = Form(False),
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
        generate_outline=generate_outline,
        outline_status="queued" if generate_outline else "not_requested",
        outline_progress_label="Waiting for transcript" if generate_outline else None,
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


@app.post("/jobs/{job_id}/outline", status_code=202)
def create_outline(job_id: str, background_tasks: BackgroundTasks):
    job = next((item for item in load_jobs() if item["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    transcript_path = Path(str(job.get("transcript_path") or ""))
    if job.get("status") != "completed" or not transcript_path.is_file():
        raise HTTPException(status_code=409, detail="Transcript is not ready")
    if job.get("outline_status") in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Outline generation is already running")
    queued = update_job(
        job_id,
        generate_outline=True,
        outline_status="queued",
        outline_started_at=None,
        outline_completed_at=None,
        outline_progress_percent=0.0,
        outline_progress_label="Queued",
        outline_eta_seconds=None,
        outline_error=None,
    )
    background_tasks.add_task(run_outline, job_id)
    return queued


@app.get("/jobs/{job_id}/outline")
def get_outline(job_id: str):
    job = next((item for item in load_jobs() if item["id"] == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    outline_path = Path(str(job.get("outline_path") or ""))
    if not outline_path.is_file():
        raise HTTPException(status_code=409, detail="Outline is not ready")
    return FileResponse(
        outline_path,
        media_type="text/markdown",
        filename=job.get("outline_name") or f"{job_id}-outline.md",
        headers={"x-outline-name": job.get("outline_name") or f"{job_id}-outline.md"},
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
    for folder in (UPLOAD_DIR, TRANSCRIPT_DIR, OUTLINE_DIR):
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
