"""
JSON store and file paths for voices and models.
"""
import json
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from tts_api.config import API_DATA_DIR

VOICES_JSON = "voices.json"
MODELS_JSON = "models.json"
VOICE_JOBS_JSON = "voice_jobs.json"
SYNTHESIS_JOBS_JSON = "synthesis_jobs.json"
AUDIOBOOK_JOBS_JSON = "audiobook_jobs.json"
VOICES_DIR = "voices"
MODELS_DIR = "models"
AUDIO_DIR = "audio"
AUDIOBOOKS_DIR = "audiobooks"
PARAGRAPH_WAV = "paragraph.wav"
SAMPLE_WAV = "sample.wav"
CHECKPOINT_DIR = "checkpoint"
TRAIN_RAW_JSONL = "train_raw.jsonl"
TRAIN_WITH_CODES_JSONL = "train_with_codes.jsonl"


def _data_dir() -> str:
    d = os.path.join(API_DATA_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _voices_dir() -> str:
    d = os.path.join(API_DATA_DIR, VOICES_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _models_dir() -> str:
    d = os.path.join(API_DATA_DIR, MODELS_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _audio_dir() -> str:
    d = os.path.join(API_DATA_DIR, AUDIO_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _audiobooks_dir() -> str:
    d = os.path.join(API_DATA_DIR, AUDIOBOOKS_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def voices_json_path() -> str:
    return os.path.join(_data_dir(), VOICES_JSON)


def models_json_path() -> str:
    return os.path.join(_data_dir(), MODELS_JSON)


def voice_jobs_json_path() -> str:
    return os.path.join(_data_dir(), VOICE_JOBS_JSON)


def synthesis_jobs_json_path() -> str:
    return os.path.join(_data_dir(), SYNTHESIS_JOBS_JSON)


def audiobook_jobs_json_path() -> str:
    return os.path.join(_data_dir(), AUDIOBOOK_JOBS_JSON)


def audiobook_dir(job_id: str) -> str:
    d = os.path.join(_audiobooks_dir(), job_id)
    os.makedirs(d, exist_ok=True)
    return d


def voice_dir(voice_id: str) -> str:
    d = os.path.join(_voices_dir(), voice_id)
    os.makedirs(d, exist_ok=True)
    return d


def voice_paragraph_path(voice_id: str) -> str:
    return os.path.join(voice_dir(voice_id), PARAGRAPH_WAV)


def model_dir(model_id: str) -> str:
    d = os.path.join(_models_dir(), model_id)
    os.makedirs(d, exist_ok=True)
    return d


def model_checkpoint_path(model_id: str, epoch: int = 2) -> str:
    """Default to checkpoint-epoch-2 (last epoch for num_epochs=3)."""
    return os.path.join(model_dir(model_id), CHECKPOINT_DIR, f"checkpoint-epoch-{epoch}")


def model_sample_path(model_id: str) -> str:
    return os.path.join(model_dir(model_id), SAMPLE_WAV)


def synthesis_audio_path(job_id: str) -> str:
    return os.path.join(_audio_dir(), f"synthesis_{job_id}.mp3")


def model_train_raw_path(model_id: str) -> str:
    return os.path.join(model_dir(model_id), TRAIN_RAW_JSONL)


def model_train_codes_path(model_id: str) -> str:
    return os.path.join(model_dir(model_id), TRAIN_WITH_CODES_JSONL)


def generate_id() -> str:
    return str(uuid.uuid4())


def _write_json_atomic(path: str, value: Any) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def slug_from_name(name: str) -> str:
    """Safe speaker_name for CustomVoice: alphanumeric and underscores only."""
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip()).strip("_")
    return s.lower() if s else "speaker"


def load_voices() -> List[Dict[str, Any]]:
    path = voices_json_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_voices(voices: List[Dict[str, Any]]) -> None:
    path = voices_json_path()
    _write_json_atomic(path, voices)


def load_models() -> List[Dict[str, Any]]:
    path = models_json_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_models(models: List[Dict[str, Any]]) -> None:
    path = models_json_path()
    _write_json_atomic(path, models)


def load_voice_jobs() -> List[Dict[str, Any]]:
    path = voice_jobs_json_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_voice_jobs(jobs: List[Dict[str, Any]]) -> None:
    path = voice_jobs_json_path()
    _write_json_atomic(path, jobs)


def get_voice_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    for job in load_voice_jobs():
        if job.get("id") == job_id:
            return job
    return None


def update_voice_job(job_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
    jobs = load_voice_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            job.update(kwargs)
            save_voice_jobs(jobs)
            return job
    return None


def delete_voice_job(job_id: str) -> Optional[Dict[str, Any]]:
    jobs = load_voice_jobs()
    kept = []
    deleted = None
    for job in jobs:
        if job.get("id") == job_id:
            deleted = job
            continue
        kept.append(job)
    if deleted is not None:
        save_voice_jobs(kept)
    return deleted


def load_synthesis_jobs() -> List[Dict[str, Any]]:
    path = synthesis_jobs_json_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_synthesis_jobs(jobs: List[Dict[str, Any]]) -> None:
    path = synthesis_jobs_json_path()
    _write_json_atomic(path, jobs)


def get_synthesis_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    for job in load_synthesis_jobs():
        if job.get("id") == job_id:
            return job
    return None


def update_synthesis_job(job_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
    jobs = load_synthesis_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            job.update(kwargs)
            save_synthesis_jobs(jobs)
            return job
    return None


def delete_synthesis_job(job_id: str) -> Optional[Dict[str, Any]]:
    jobs = load_synthesis_jobs()
    kept = []
    deleted = None
    for job in jobs:
        if job.get("id") == job_id:
            deleted = job
            continue
        kept.append(job)
    if deleted is not None:
        path = deleted.get("output_path")
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
        save_synthesis_jobs(kept)
    return deleted


def load_audiobook_jobs() -> List[Dict[str, Any]]:
    path = audiobook_jobs_json_path()
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_audiobook_jobs(jobs: List[Dict[str, Any]]) -> None:
    path = audiobook_jobs_json_path()
    _write_json_atomic(path, jobs)


def get_audiobook_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    for job in load_audiobook_jobs():
        if job.get("id") == job_id:
            return job
    return None


def update_audiobook_job(job_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
    jobs = load_audiobook_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            job.update(kwargs)
            save_audiobook_jobs(jobs)
            return job
    return None


def update_audiobook_chunk(job_id: str, index: int, **kwargs: Any) -> Optional[Dict[str, Any]]:
    jobs = load_audiobook_jobs()
    for job in jobs:
        if job.get("id") != job_id:
            continue
        for chunk in job.get("chunks", []):
            if int(chunk.get("index", -1)) == int(index):
                chunk.update(kwargs)
                completed = sum(1 for c in job.get("chunks", []) if c.get("status") == "completed")
                failed = sum(1 for c in job.get("chunks", []) if c.get("status") == "failed")
                total = max(1, int(job.get("total_chunks") or len(job.get("chunks", [])) or 1))
                job["completed_chunks"] = completed
                job["failed_chunks"] = failed
                job["progress_percent"] = round((completed / total) * 100, 1)
                job["updated_at"] = kwargs.get("updated_at", job.get("updated_at"))
                save_audiobook_jobs(jobs)
                return chunk
    return None


def delete_audiobook_job(job_id: str) -> Optional[Dict[str, Any]]:
    jobs = load_audiobook_jobs()
    kept = []
    deleted = None
    for job in jobs:
        if job.get("id") == job_id:
            deleted = job
            continue
        kept.append(job)
    if deleted is not None:
        import shutil
        d = os.path.join(_audiobooks_dir(), job_id)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        save_audiobook_jobs(kept)
    return deleted


def get_voice_by_id(voice_id: str) -> Optional[Dict[str, Any]]:
    for v in load_voices():
        if v.get("id") == voice_id:
            return v
    return None


def get_voice_by_name(name: str) -> Optional[Dict[str, Any]]:
    n = (name or "").strip()
    if not n:
        return None
    for v in load_voices():
        if (v.get("name") or "").strip() == n:
            return v
    return None


def get_model_by_id(model_id: str) -> Optional[Dict[str, Any]]:
    for m in load_models():
        if m.get("id") == model_id:
            return m
    return None


def get_model_by_name(name: str) -> Optional[Dict[str, Any]]:
    n = (name or "").strip()
    if not n:
        return None
    for m in load_models():
        if (m.get("name") or "").strip() == n:
            return m
    return None


def default_voice_name(voice_id: str) -> str:
    return f"voice_{voice_id[:8]}"


def default_model_name(model_id: str) -> str:
    return f"model_{model_id[:8]}"


def update_model(model_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
    """Update fields of a model by id. Saves and returns updated record or None."""
    models = load_models()
    for m in models:
        if m.get("id") == model_id:
            m.update(kwargs)
            save_models(models)
            return m
    return None
