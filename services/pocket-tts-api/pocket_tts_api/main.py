from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import scipy.io.wavfile
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pocket_tts import TTSModel, export_model_state
from pydantic import BaseModel, Field


DATA_DIR = Path(os.environ.get("POCKET_TTS_DATA", "/models/pocket-tts/data"))
CACHE_DIR = Path(os.environ.get("HF_HOME", "/models/pocket-tts/cache"))
OUTPUT_DIR = DATA_DIR / "outputs"
VOICE_DIR = DATA_DIR / "voices"
JOBS_PATH = DATA_DIR / "jobs.json"
VOICES_PATH = DATA_DIR / "voices.json"
MAX_TEXT_CHARS = int(os.environ.get("POCKET_TTS_MAX_TEXT_CHARS", "50000"))

BUILTIN_VOICES = [
    ("alba", "Alba", "English"), ("anna", "Anna", "English"),
    ("azelma", "Azelma", "English"), ("bill_boerst", "Bill Boerst", "English"),
    ("caro_davy", "Caro Davy", "English"), ("charles", "Charles", "English"),
    ("cosette", "Cosette", "English"), ("eponine", "Eponine", "English"),
    ("eve", "Eve", "English"), ("fantine", "Fantine", "English"),
    ("george", "George", "English"), ("jane", "Jane", "English"),
    ("javert", "Javert", "English"), ("jean", "Jean", "English"),
    ("marius", "Marius", "English"), ("mary", "Mary", "English"),
    ("michael", "Michael", "English"), ("paul", "Paul", "English"),
    ("peter_yearsley", "Peter Yearsley", "English"),
    ("stuart_bell", "Stuart Bell", "English"), ("vera", "Vera", "English"),
    ("estelle", "Estelle", "French"), ("juergen", "Juergen", "German"),
    ("giovanni", "Giovanni", "Italian"), ("rafael", "Rafael", "Portuguese"),
    ("lola", "Lola", "Spanish"),
]
LANGUAGE_CONFIG = {
    "English": "english", "French": "french_24l", "German": "german_24l",
    "Italian": "italian_24l", "Portuguese": "portuguese_24l", "Spanish": "spanish_24l",
}

for path in (DATA_DIR, CACHE_DIR, OUTPUT_DIR, VOICE_DIR):
    path.mkdir(parents=True, exist_ok=True)

store_lock = threading.RLock()
generation_lock = threading.Lock()
model_lock = threading.Lock()
models: dict[str, TTSModel] = {}
voice_states: dict[tuple[str, str], dict[str, Any]] = {}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> list[dict[str, Any]]:
    with store_lock:
        if not path.exists():
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, json.JSONDecodeError):
            return []


def write_json(path: Path, value: list[dict[str, Any]]) -> None:
    with store_lock:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temporary.replace(path)


def update_job(job_id: str, **changes: Any) -> dict[str, Any] | None:
    jobs = read_json(JOBS_PATH)
    for job in jobs:
        if job.get("id") == job_id:
            job.update(changes, updated_at=utcnow())
            write_json(JOBS_PATH, jobs)
            return job
    return None


def get_model(language: str) -> TTSModel:
    config = LANGUAGE_CONFIG.get(language)
    if not config:
        raise ValueError(f"Unsupported language: {language}")
    with model_lock:
        if config not in models:
            models[config] = TTSModel.load_model(language=config)
        return models[config]


def all_voices() -> list[dict[str, Any]]:
    builtins = [
        {"id": f"builtin:{voice_id}", "name": name, "language": language, "kind": "builtin", "source": voice_id}
        for voice_id, name, language in BUILTIN_VOICES
    ]
    return builtins + read_json(VOICES_PATH)


def resolve_voice(voice_id: str) -> dict[str, Any]:
    voice = next((item for item in all_voices() if item.get("id") == voice_id), None)
    if not voice:
        raise ValueError("Pocket TTS voice not found.")
    return voice


def get_voice_state(model: TTSModel, voice: dict[str, Any]) -> dict[str, Any]:
    key = (voice["id"], voice["language"])
    if key not in voice_states:
        source = voice["source"]
        voice_states[key] = model.get_state_for_audio_prompt(source)
    return voice_states[key]


def run_job(job_id: str) -> None:
    started = time.monotonic()
    job = next((item for item in read_json(JOBS_PATH) if item.get("id") == job_id), None)
    if not job:
        return
    try:
        update_job(job_id, status="running", progress_percent=5, progress_label="Waiting for CPU", started_at=utcnow())
        with generation_lock:
            update_job(job_id, progress_percent=15, progress_label="Loading Pocket TTS model")
            voice = resolve_voice(job["voice_id"])
            model = get_model(voice["language"])
            update_job(job_id, progress_percent=30, progress_label="Loading voice state")
            state = get_voice_state(model, voice)
            update_job(job_id, progress_percent=45, progress_label="Generating speech")
            audio = model.generate_audio(state, job["text"], max_tokens=50)
            output_path = OUTPUT_DIR / f"{job_id}.wav"
            scipy.io.wavfile.write(output_path, model.sample_rate, audio.detach().cpu().numpy())
        elapsed = time.monotonic() - started
        duration = len(audio) / model.sample_rate
        update_job(
            job_id, status="completed", progress_percent=100, progress_label="Complete",
            elapsed_seconds=round(elapsed, 2), duration_seconds=round(duration, 2),
            output_path=str(output_path), output_bytes=output_path.stat().st_size,
            finished_at=utcnow(), error=None,
        )
    except Exception as exc:
        update_job(
            job_id, status="failed", progress_percent=100, progress_label="Failed",
            elapsed_seconds=round(time.monotonic() - started, 2), finished_at=utcnow(), error=str(exc),
        )


def export_uploaded_voice(voice_id: str, source_path: Path, language: str) -> Path:
    normalized = VOICE_DIR / f"{voice_id}.wav"
    state_path = VOICE_DIR / f"{voice_id}.safetensors"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source_path), "-ac", "1", "-ar", "24000", str(normalized)],
            check=True, capture_output=True,
        )
        model = get_model(language)
        state = model.get_state_for_audio_prompt(normalized)
        export_model_state(state, state_path)
    finally:
        normalized.unlink(missing_ok=True)
    return state_path


class CreateJobBody(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    voice_id: str


@asynccontextmanager
async def lifespan(_: FastAPI):
    jobs = read_json(JOBS_PATH)
    changed = False
    for job in jobs:
        if job.get("status") in {"queued", "running"}:
            job.update(status="failed", progress_percent=100, progress_label="Interrupted", error="Pocket TTS service restarted before completion.", finished_at=utcnow(), updated_at=utcnow())
            changed = True
    if changed:
        write_json(JOBS_PATH, jobs)
    yield


app = FastAPI(title="GPU45 Pocket TTS API", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "engine": "pocket-tts", "device": "cpu", "model_loaded": bool(models)}


@app.get("/voices")
def voices() -> list[dict[str, Any]]:
    return all_voices()


@app.post("/voices", status_code=201)
async def create_voice(name: str = Form(...), language: str = Form("English"), file: UploadFile = File(...)) -> dict[str, Any]:
    if language not in LANGUAGE_CONFIG:
        raise HTTPException(status_code=400, detail="Unsupported language.")
    voice_id = uuid.uuid4().hex
    suffix = Path(file.filename or "voice.wav").suffix or ".wav"
    source_path = VOICE_DIR / f"{voice_id}.upload{suffix}"
    try:
        with source_path.open("wb") as target:
            shutil.copyfileobj(file.file, target)
        state_path = export_uploaded_voice(voice_id, source_path, language)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Voice import failed: {exc}") from exc
    finally:
        source_path.unlink(missing_ok=True)
    voice = {"id": f"clone:{voice_id}", "name": name.strip() or "Cloned voice", "language": language, "kind": "clone", "source": str(state_path), "created_at": utcnow()}
    items = read_json(VOICES_PATH)
    items.append(voice)
    write_json(VOICES_PATH, items)
    return voice


@app.delete("/voices/{voice_id}")
def delete_voice(voice_id: str) -> dict[str, bool]:
    full_id = f"clone:{voice_id}" if not voice_id.startswith("clone:") else voice_id
    items = read_json(VOICES_PATH)
    voice = next((item for item in items if item.get("id") == full_id), None)
    if not voice:
        raise HTTPException(status_code=404, detail="Cloned voice not found.")
    Path(str(voice.get("source", ""))).unlink(missing_ok=True)
    write_json(VOICES_PATH, [item for item in items if item.get("id") != full_id])
    voice_states.pop((full_id, voice["language"]), None)
    return {"ok": True}


@app.get("/jobs")
def jobs() -> list[dict[str, Any]]:
    return list(reversed(read_json(JOBS_PATH)))


@app.post("/jobs", status_code=202)
def create_job(body: CreateJobBody) -> dict[str, Any]:
    voice = resolve_voice(body.voice_id)
    job_id = uuid.uuid4().hex
    created = utcnow()
    job = {
        "id": job_id, "kind": "pocket_synthesis", "engine": "pocket-tts", "status": "queued",
        "voice_id": voice["id"], "voice_name": voice["name"], "language": voice["language"],
        "text": body.text.strip(), "text_chars": len(body.text.strip()), "progress_percent": 0,
        "progress_label": "Queued", "created_at": created, "updated_at": created,
    }
    items = read_json(JOBS_PATH)
    items.append(job)
    write_json(JOBS_PATH, items)
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()
    return job


@app.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, bool]:
    items = read_json(JOBS_PATH)
    job = next((item for item in items if item.get("id") == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.get("status") in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Active Pocket TTS jobs cannot be deleted.")
    output_path = job.get("output_path")
    if output_path:
        Path(str(output_path)).unlink(missing_ok=True)
    write_json(JOBS_PATH, [item for item in items if item.get("id") != job_id])
    return {"ok": True}


@app.get("/jobs/{job_id}/audio")
def job_audio(job_id: str, download: bool = False) -> FileResponse:
    job = next((item for item in read_json(JOBS_PATH) if item.get("id") == job_id), None)
    if not job or job.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Completed audio not found.")
    path = Path(str(job.get("output_path", "")))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file is missing.")
    return FileResponse(path, media_type="audio/wav", filename=f"pocket-tts-{job_id}.wav" if download else None)
