"""
TTS Generator API: voices, models, synthesize. Run as a service bound to 0.0.0.0.
"""
import os
import shutil
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from time import monotonic

from fastapi import FastAPI, HTTPException, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from tts_api.audio_convert import wav_to_mp3_bytes
from tts_api.config import BUILTIN_SPEAKERS
from tts_api import store
from tts_api import voices as voices_module
from tts_api import models as models_module
from tts_api import synthesize as synthesize_module
from tts_api import document_tts


# Request/response schemas
class CreateVoiceBody(BaseModel):
    instruct: str = Field(..., description="Voice instruction/prompt for VoiceDesign")
    language: str = Field(default="English", description="Language code")
    name: str | None = Field(default=None, description="Optional display name (must be unique)")
    device: str | None = Field(default=None, description="Optional device override: cpu or cuda:0")


class RenameBody(BaseModel):
    name: str = Field(..., description="New unique name")


class CreateModelBody(BaseModel):
    voice_id: str = Field(..., description="Voice to train from")
    name: str | None = Field(default=None, description="Optional display name (must be unique)")


class SynthesizeBody(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    voice_id: str | None = Field(default=None, description="Use this voice (VoiceDesign)")
    model_id: str | None = Field(default=None, description="Use this trained model (CustomVoice)")
    use_default: bool = Field(default=False, description="Use default VoiceDesign with no instruct")


class SynthesisJobBody(BaseModel):
    text: str = Field(..., description="Text to synthesize")
    model_id: str = Field(..., description="Ready CustomVoice model to use")


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _estimate_synthesis_seconds(model_id: str, text: str) -> float:
    chars = max(1, len(text or ""))
    completed = [
        job for job in store.load_synthesis_jobs()
        if job.get("status") == "completed"
        and job.get("model_id") == model_id
        and isinstance(job.get("duration_seconds"), (int, float))
        and int(job.get("text_chars") or 0) > 0
    ]
    if completed:
        rates = [float(job["duration_seconds"]) / max(1, int(job.get("text_chars") or 1)) for job in completed[-10:]]
        seconds_per_char = sum(rates) / len(rates)
        return max(8.0, min(900.0, seconds_per_char * chars))
    return max(20.0, min(900.0, 0.45 * chars))


@asynccontextmanager
async def lifespan(app: FastAPI):
    now = _utcnow()
    jobs = store.load_voice_jobs()
    changed = False
    for job in jobs:
        if job.get("status") in ("queued", "running"):
            job.update(
                status="failed",
                error="TTS service restarted before this job finished.",
                progress_label="Interrupted",
                eta_seconds=0.0,
                finished_at=now,
                updated_at=now,
            )
            changed = True
    if changed:
        store.save_voice_jobs(jobs)
    models = store.load_models()
    models_changed = False
    for model in models:
        if model.get("status") == "training":
            model.update(
                status="failed",
                error="TTS service restarted before this model finished training.",
                progress_label="Interrupted",
                eta_seconds=0.0,
                finished_at=now,
                updated_at=now,
            )
            models_changed = True
    if models_changed:
        store.save_models(models)
    synthesis_jobs = store.load_synthesis_jobs()
    synthesis_changed = False
    for job in synthesis_jobs:
        if job.get("status") in ("queued", "running"):
            job.update(
                status="failed",
                error="TTS service restarted before this synthesis job finished.",
                progress_label="Interrupted",
                progress_percent=100.0,
                eta_seconds=0.0,
                finished_at=now,
                updated_at=now,
            )
            synthesis_changed = True
    if synthesis_changed:
        store.save_synthesis_jobs(synthesis_jobs)
    audiobook_jobs = store.load_audiobook_jobs()
    audiobook_changed = False
    for job in audiobook_jobs:
        if job.get("status") in ("queued", "running"):
            job.update(
                status="stopped",
                progress_label="Interrupted by service restart",
                stop_requested=False,
                updated_at=now,
            )
            audiobook_changed = True
    if audiobook_changed:
        store.save_audiobook_jobs(audiobook_jobs)
    yield
    # Optional: clear model cache on shutdown
    pass


app = FastAPI(
    title="Qwen3-TTS Generator API",
    description=(
        "Create voices from prompts, train CustomVoice models from those voices, "
        "and synthesize speech. Default synthesis uses VoiceDesign with empty instruct. "
        "Set QWEN_TTS_API_DATA for data directory, QWEN_TTS_DEVICE for device (default cuda:0). "
        "Bind to 0.0.0.0 to allow LAN access."
    ),
    lifespan=lifespan,
)


@app.get("/")
def root():
    """Root path: point to docs and health so visitors do not get 404."""
    return {
        "service": "Qwen3-TTS Generator API",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    """Health check for service monitoring."""
    return {"status": "ok"}


def _run_create_voice_job(job_id: str, body: CreateVoiceBody) -> None:
    started = monotonic()

    def update_progress(label: str, percent: float, eta_seconds: float | None = None) -> None:
        elapsed = monotonic() - started
        store.update_voice_job(
            job_id,
            progress_label=label,
            progress_percent=round(max(0.0, min(100.0, percent)), 1),
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=round(eta_seconds, 1) if eta_seconds is not None else None,
            updated_at=_utcnow(),
        )

    try:
        store.update_voice_job(
            job_id,
            status="running",
            progress_label="Starting",
            progress_percent=2.0,
            started_at=_utcnow(),
            updated_at=_utcnow(),
        )
        voice = voices_module.create_voice(
            instruct=body.instruct,
            language=body.language,
            name=body.name,
            device=body.device,
            progress=update_progress,
        )
        elapsed = monotonic() - started
        store.update_voice_job(
            job_id,
            status="complete",
            voice_id=voice["id"],
            voice=voice,
            progress_label="Complete",
            progress_percent=100.0,
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=0.0,
            finished_at=_utcnow(),
            updated_at=_utcnow(),
        )
    except Exception as e:
        elapsed = monotonic() - started
        store.update_voice_job(
            job_id,
            status="failed",
            error=str(e),
            progress_label="Failed",
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=0.0,
            finished_at=_utcnow(),
            updated_at=_utcnow(),
        )


def _run_import_voice_job(job_id: str, source_path: str, source_filename: str, name: str, language: str, transcript: str | None) -> None:
    started = monotonic()

    def update_progress(label: str, percent: float, eta_seconds: float | None = None) -> None:
        elapsed = monotonic() - started
        store.update_voice_job(
            job_id,
            progress_label=label,
            progress_percent=round(max(0.0, min(100.0, percent)), 1),
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=round(eta_seconds, 1) if eta_seconds is not None else None,
            updated_at=_utcnow(),
        )

    try:
        store.update_voice_job(
            job_id,
            status="running",
            progress_label="Starting upload import",
            progress_percent=2.0,
            started_at=_utcnow(),
            updated_at=_utcnow(),
        )
        voice = voices_module.import_voice_from_media(
            source_path=source_path,
            source_filename=source_filename,
            name=name,
            language=language,
            transcript=transcript,
            progress=update_progress,
        )
        elapsed = monotonic() - started
        store.update_voice_job(
            job_id,
            status="complete",
            voice_id=voice["id"],
            voice=voice,
            progress_label="Complete",
            progress_percent=100.0,
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=0.0,
            finished_at=_utcnow(),
            updated_at=_utcnow(),
        )
    except Exception as e:
        elapsed = monotonic() - started
        store.update_voice_job(
            job_id,
            status="failed",
            error=str(e),
            progress_label="Failed",
            progress_percent=100.0,
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=0.0,
            finished_at=_utcnow(),
            updated_at=_utcnow(),
        )
    finally:
        try:
            os.remove(source_path)
        except OSError:
            pass


# Voices
@app.post("/voices", status_code=202)
def create_voice(body: CreateVoiceBody, background_tasks: BackgroundTasks):
    """Queue creation of a voice from a prompt. Poll GET /voice-jobs/{job_id}."""
    try:
        voice_name = (body.name or "").strip()
        if voice_name and store.get_voice_by_name(voice_name):
            raise ValueError(f"Voice name already exists: {voice_name}")
        job_id = store.generate_id()
        job = {
            "id": job_id,
            "kind": "voice",
            "status": "queued",
            "name": body.name,
            "language": body.language or "English",
            "device": body.device or os.environ.get("QWEN_TTS_DEVICE", "cpu"),
            "progress_label": "Queued",
            "progress_percent": 1.0,
            "eta_seconds": None,
            "elapsed_seconds": 0.0,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        jobs = store.load_voice_jobs()
        jobs.append(job)
        store.save_voice_jobs(jobs)
        background_tasks.add_task(_run_create_voice_job, job_id, body)
        return {"job_id": job_id, "status": "queued", "message": "Poll GET /voice-jobs/{job_id} for progress."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/voices/import", status_code=202)
async def import_voice(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    name: str = Form(...),
    language: str = Form("English"),
    transcript: str | None = Form(None),
):
    """Queue import of an external audio/video file as a trainable voice."""
    voice_name = (name or "").strip()
    if not voice_name:
        raise HTTPException(status_code=400, detail="Voice name is required")
    if store.get_voice_by_name(voice_name):
        raise HTTPException(status_code=400, detail=f"Voice name already exists: {voice_name}")

    suffix = Path(file.filename or "upload.media").suffix or ".media"
    with tempfile.NamedTemporaryFile(prefix="tts-voice-import-", suffix=suffix, delete=False) as target:
        shutil.copyfileobj(file.file, target)
        source_path = target.name

    job_id = store.generate_id()
    job = {
        "id": job_id,
        "kind": "voice_import",
        "status": "queued",
        "name": voice_name,
        "language": language or "English",
        "device": "import",
        "source_filename": file.filename or "upload",
        "transcript_source": "submitted" if (transcript or "").strip() else "whisper",
        "progress_label": "Queued",
        "progress_percent": 1.0,
        "eta_seconds": None,
        "elapsed_seconds": 0.0,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    jobs = store.load_voice_jobs()
    jobs.append(job)
    store.save_voice_jobs(jobs)
    background_tasks.add_task(_run_import_voice_job, job_id, source_path, file.filename or "upload", voice_name, language or "English", transcript)
    return {"job_id": job_id, "status": "queued", "message": "Poll GET /voice-jobs/{job_id} for progress."}


@app.get("/voices")
def list_voices():
    """List all voices created via the API (POST /voices)."""
    return store.load_voices()


@app.get("/voice-jobs")
def list_voice_jobs():
    """List voice generation jobs."""
    return store.load_voice_jobs()


@app.get("/voice-jobs/{job_id}")
def get_voice_job(job_id: str):
    """Get voice generation job metadata and progress."""
    job = store.get_voice_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Voice job not found")
    return job


@app.delete("/voice-jobs/{job_id}", status_code=204)
def delete_voice_job(job_id: str):
    """Delete a completed or failed voice generation job record."""
    job = store.get_voice_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Voice job not found")
    if job.get("status") in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Voice job is still running")
    store.delete_voice_job(job_id)


@app.get("/voices/builtin")
def list_builtin_speakers():
    """List built-in speakers from the CustomVoice model (reference only; not used for synthesis in this API)."""
    return {"speakers": BUILTIN_SPEAKERS}


@app.get("/voices/{voice_id}")
def get_voice(voice_id: str):
    """Get voice metadata."""
    v = store.get_voice_by_id(voice_id)
    if not v:
        raise HTTPException(status_code=404, detail="Voice not found")
    return v


@app.get("/voices/{voice_id}/sample", response_class=Response)
def get_voice_sample(voice_id: str):
    """Return the paragraph audio as MP3 for this voice (to preview before training a model)."""
    v = store.get_voice_by_id(voice_id)
    if not v:
        raise HTTPException(status_code=404, detail="Voice not found")
    path = v.get("paragraph_path")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Voice sample file not found")
    mp3_bytes = wav_to_mp3_bytes(path)
    return Response(content=mp3_bytes, media_type="audio/mpeg")


@app.patch("/voices/{voice_id}")
def rename_voice(voice_id: str, body: RenameBody):
    """Rename a voice. Name must be unique."""
    try:
        return voices_module.rename_voice(voice_id, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/voices/{voice_id}", status_code=204)
def delete_voice(voice_id: str):
    """Delete a voice and its paragraph audio."""
    try:
        voices_module.delete_voice(voice_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


# Models (training is async; POST returns 202 with model id; poll GET /models/{id} for status)
def _run_training_task(voice_id: str, model_id: str, model_name: str) -> None:
    """Run in thread: train then update model record or set status failed."""
    started = monotonic()

    def update_progress(label: str, percent: float, eta_seconds: float | None = None) -> None:
        elapsed = monotonic() - started
        store.update_model(
            model_id,
            progress_label=label,
            progress_percent=round(max(0.0, min(100.0, percent)), 1),
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=round(eta_seconds, 1) if eta_seconds is not None else None,
            updated_at=_utcnow(),
        )

    try:
        store.update_model(
            model_id,
            status="training",
            progress_label="Starting",
            progress_percent=2.0,
            started_at=_utcnow(),
            updated_at=_utcnow(),
        )
        record = models_module.run_training_sync(voice_id, model_id, model_name, progress=update_progress)
        elapsed = monotonic() - started
        store.update_model(
            model_id,
            status="ready",
            progress_label="Complete",
            progress_percent=100.0,
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=0.0,
            finished_at=_utcnow(),
            updated_at=_utcnow(),
            **{k: v for k, v in record.items() if k != "id"},
        )
    except Exception as e:
        elapsed = monotonic() - started
        store.update_model(
            model_id,
            status="failed",
            error=str(e),
            progress_label="Failed",
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=0.0,
            finished_at=_utcnow(),
            updated_at=_utcnow(),
        )


@app.post("/models", status_code=202)
def create_model(body: CreateModelBody, background_tasks: BackgroundTasks):
    """
    Start training a CustomVoice model from a voice. Returns 202 with model id.
    Poll GET /models/{model_id} until status is 'ready' or 'failed'.
    """
    voice = store.get_voice_by_id(body.voice_id)
    if not voice:
        raise HTTPException(status_code=404, detail="Voice not found")
    model_id = store.generate_id()
    model_name = (body.name or "").strip() or store.default_model_name(model_id)
    if store.get_model_by_name(model_name):
        raise HTTPException(status_code=400, detail=f"Model name already exists: {model_name}")

    placeholder = {
        "id": model_id,
        "name": model_name,
        "voice_id": body.voice_id,
        "status": "training",
        "progress_label": "Queued",
        "progress_percent": 1.0,
        "eta_seconds": None,
        "elapsed_seconds": 0.0,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    models_list = store.load_models()
    models_list.append(placeholder)
    store.save_models(models_list)

    background_tasks.add_task(_run_training_task, body.voice_id, model_id, model_name)
    return {"model_id": model_id, "status": "training", "message": "Poll GET /models/{model_id} for status."}


@app.get("/models")
def list_models():
    """List all models (including those still training)."""
    return store.load_models()


@app.get("/models/{model_id}")
def get_model(model_id: str):
    """Get model metadata. Check 'status' for 'ready', 'training', or 'failed'."""
    m = store.get_model_by_id(model_id)
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    return m


@app.get("/models/{model_id}/sample", response_class=Response)
def get_model_sample(model_id: str):
    """Return the sample sentence audio as MP3 for this model (only when status is ready)."""
    m = store.get_model_by_id(model_id)
    if not m:
        raise HTTPException(status_code=404, detail="Model not found")
    if m.get("status") == "training":
        raise HTTPException(status_code=409, detail="Model still training")
    if m.get("status") == "failed":
        raise HTTPException(status_code=409, detail="Model training failed")
    path = m.get("sample_path")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Model sample file not found")
    mp3_bytes = wav_to_mp3_bytes(path)
    return Response(content=mp3_bytes, media_type="audio/mpeg")


@app.patch("/models/{model_id}")
def rename_model(model_id: str, body: RenameBody):
    """Rename a model (display name only)."""
    try:
        return models_module.rename_model(model_id, body.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: str):
    """Delete a model and its checkpoint/sample files."""
    try:
        models_module.delete_model(model_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _run_synthesis_job(job_id: str, body: SynthesisJobBody) -> None:
    started = monotonic()
    stop_monitor = threading.Event()
    estimated = _estimate_synthesis_seconds(body.model_id, body.text)

    def update_progress(label: str, percent: float, eta_seconds: float | None = None) -> None:
        elapsed = monotonic() - started
        store.update_synthesis_job(
            job_id,
            progress_label=label,
            progress_percent=round(max(0.0, min(100.0, percent)), 1),
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=round(eta_seconds, 1) if eta_seconds is not None else None,
            updated_at=_utcnow(),
        )

    def monitor() -> None:
        while not stop_monitor.wait(1):
            elapsed = monotonic() - started
            fraction = min(0.96, elapsed / max(1.0, estimated))
            update_progress("Generating audio", 5.0 + (fraction * 90.0), max(0.0, estimated - elapsed))

    try:
        model = store.get_model_by_id(body.model_id)
        if not model:
            raise KeyError(f"Model not found: {body.model_id}")
        if model.get("status") != "ready":
            raise ValueError("Model is not ready.")
        store.update_synthesis_job(
            job_id,
            status="running",
            progress_label="Starting",
            progress_percent=2.0,
            eta_seconds=round(estimated, 1),
            started_at=_utcnow(),
            updated_at=_utcnow(),
        )
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        wav_bytes, _ = synthesize_module.synthesize(
            text=body.text,
            model_id=body.model_id,
        )
        stop_monitor.set()
        update_progress("Encoding MP3", 97.0, 1.0)
        mp3_bytes = wav_to_mp3_bytes(wav_bytes)
        output_path = store.synthesis_audio_path(job_id)
        with open(output_path, "wb") as f:
            f.write(mp3_bytes)
        elapsed = monotonic() - started
        store.update_synthesis_job(
            job_id,
            status="completed",
            progress_label="Complete",
            progress_percent=100.0,
            elapsed_seconds=round(elapsed, 1),
            duration_seconds=round(elapsed, 1),
            eta_seconds=0.0,
            output_path=output_path,
            output_bytes=len(mp3_bytes),
            finished_at=_utcnow(),
            updated_at=_utcnow(),
        )
    except Exception as e:
        stop_monitor.set()
        elapsed = monotonic() - started
        store.update_synthesis_job(
            job_id,
            status="failed",
            error=str(e),
            progress_label="Failed",
            progress_percent=100.0,
            elapsed_seconds=round(elapsed, 1),
            eta_seconds=0.0,
            finished_at=_utcnow(),
            updated_at=_utcnow(),
        )


@app.post("/synthesis-jobs", status_code=202)
def create_synthesis_job(body: SynthesisJobBody, background_tasks: BackgroundTasks):
    model = store.get_model_by_id(body.model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.get("status") != "ready":
        raise HTTPException(status_code=409, detail="Model is not ready")
    job_id = store.generate_id()
    estimate = _estimate_synthesis_seconds(body.model_id, body.text)
    job = {
        "id": job_id,
        "kind": "synthesis",
        "status": "queued",
        "model_id": body.model_id,
        "model_name": model.get("name"),
        "text": body.text,
        "text_source": "submitted",
        "text_chars": len(body.text or ""),
        "progress_label": "Queued",
        "progress_percent": 1.0,
        "eta_seconds": round(estimate, 1),
        "elapsed_seconds": 0.0,
        "created_at": _utcnow(),
        "updated_at": _utcnow(),
    }
    jobs = store.load_synthesis_jobs()
    jobs.append(job)
    store.save_synthesis_jobs(jobs)
    background_tasks.add_task(_run_synthesis_job, job_id, body)
    return job


@app.get("/synthesis-jobs")
def list_synthesis_jobs():
    return store.load_synthesis_jobs()


@app.get("/synthesis-jobs/{job_id}")
def get_synthesis_job(job_id: str):
    job = store.get_synthesis_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Synthesis job not found")
    return job


@app.get("/synthesis-jobs/{job_id}/audio", response_class=Response)
def get_synthesis_job_audio(job_id: str):
    job = store.get_synthesis_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Synthesis job not found")
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Synthesis job is not complete")
    output_path = job.get("output_path")
    if not output_path or not os.path.isfile(output_path):
        raise HTTPException(status_code=404, detail="Synthesis audio file not found")
    return FileResponse(output_path, media_type="audio/mpeg", filename=f"synthesis_{job_id}.mp3")


@app.delete("/synthesis-jobs/{job_id}", status_code=204)
def delete_synthesis_job(job_id: str):
    job = store.get_synthesis_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Synthesis job not found")
    if job.get("status") in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Synthesis job is still running")
    store.delete_synthesis_job(job_id)


# Audiobooks / long document TTS
@app.post("/audiobooks", status_code=202)
async def create_audiobook(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    model_id: str = Form(...),
    title: str | None = Form(None),
    chunk_chars: int = Form(700),
):
    suffix = Path(file.filename or "upload.txt").suffix or ".txt"
    with tempfile.NamedTemporaryFile(prefix="tts-audiobook-upload-", suffix=suffix, delete=False) as target:
        shutil.copyfileobj(file.file, target)
        source_path = target.name
    try:
        job = document_tts.create_audiobook_job(
            source_path=source_path,
            source_filename=file.filename or "upload",
            model_id=model_id,
            title=title,
            chunk_chars=chunk_chars,
        )
    except KeyError as e:
        try:
            os.remove(source_path)
        except OSError:
            pass
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        try:
            os.remove(source_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            os.remove(source_path)
        except OSError:
            pass
    background_tasks.add_task(document_tts.run_audiobook_job, job["id"])
    return job


@app.get("/audiobooks")
def list_audiobooks():
    return store.load_audiobook_jobs()


@app.get("/audiobooks/{job_id}")
def get_audiobook(job_id: str):
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Audiobook job not found")
    return job


@app.post("/audiobooks/{job_id}/stop")
def stop_audiobook(job_id: str):
    try:
        return document_tts.request_stop(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/audiobooks/{job_id}/resume", status_code=202)
def resume_audiobook(job_id: str, background_tasks: BackgroundTasks):
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Audiobook job not found")
    if job.get("status") in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Audiobook job is already running")
    store.update_audiobook_job(job_id, status="queued", stop_requested=False, progress_label="Queued for resume", updated_at=_utcnow())
    background_tasks.add_task(document_tts.run_audiobook_job, job_id)
    return store.get_audiobook_job_by_id(job_id)


@app.get("/audiobooks/{job_id}/chunks/{index}/audio")
def get_audiobook_chunk_audio(job_id: str, index: int):
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Audiobook job not found")
    chunk = next((c for c in job.get("chunks", []) if int(c.get("index", -1)) == int(index)), None)
    if not chunk:
        raise HTTPException(status_code=404, detail="Audiobook chunk not found")
    path = chunk.get("output_path")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Audiobook chunk audio not found")
    return FileResponse(path, media_type="audio/mpeg", filename=f"{job_id}_chunk_{index:05d}.mp3")


@app.get("/audiobooks/{job_id}/audio")
def get_audiobook_audio(job_id: str):
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Audiobook job not found")
    path = job.get("stitched_output_path")
    if not path or not os.path.isfile(path):
        path = document_tts.stitch_completed_chunks(job_id)
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="No completed audiobook audio is available yet")
    return FileResponse(path, media_type="audio/mpeg", filename=f"audiobook_{job_id}.mp3")


@app.delete("/audiobooks/{job_id}", status_code=204)
def delete_audiobook(job_id: str):
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Audiobook job not found")
    if job.get("status") in ("queued", "running"):
        raise HTTPException(status_code=409, detail="Stop the audiobook job before deleting it")
    store.delete_audiobook_job(job_id)


# Synthesize
@app.post("/synthesize", response_class=Response)
def synthesize(body: SynthesizeBody):
    """
    Generate speech as MP3. Provide exactly one of voice_id, model_id, or use_default=true.
    Returns audio/mpeg.
    """
    if body.voice_id and body.model_id:
        raise HTTPException(status_code=400, detail="Specify only one of voice_id, model_id, or use_default")
    if body.voice_id and body.use_default:
        raise HTTPException(status_code=400, detail="Specify only one of voice_id, model_id, or use_default")
    if body.model_id and body.use_default:
        raise HTTPException(status_code=400, detail="Specify only one of voice_id, model_id, or use_default")
    if not body.voice_id and not body.model_id and not body.use_default:
        raise HTTPException(status_code=400, detail="Specify one of voice_id, model_id, or use_default=true")

    try:
        wav_bytes, _ = synthesize_module.synthesize(
            text=body.text,
            voice_id=body.voice_id,
            model_id=body.model_id,
            use_default=body.use_default,
        )
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))

    mp3_bytes = wav_to_mp3_bytes(wav_bytes)
    return Response(content=mp3_bytes, media_type="audio/mpeg")


def run():
    """Entry point for qwen-tts-api script. Bind to 0.0.0.0 for LAN access."""
    import uvicorn
    host = os.environ.get("QWEN_TTS_API_HOST", "0.0.0.0")
    port = int(os.environ.get("QWEN_TTS_API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run()
