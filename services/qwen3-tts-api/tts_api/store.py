"""
JSON store and file paths for voices and models.
"""
import json
import os
import re
import shutil
import sqlite3
import stat
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from tts_api.config import API_DATA_DIR

VOICES_JSON = "voices.json"
MODELS_JSON = "models.json"
VOICE_JOBS_JSON = "voice_jobs.json"
SYNTHESIS_JOBS_JSON = "synthesis_jobs.json"
AUDIOBOOK_JOBS_JSON = "audiobook_jobs.json"
PRESENTATION_JOBS_JSON = "presentation_jobs.json"
VOICES_DIR = "voices"
MODELS_DIR = "models"
AUDIO_DIR = "audio"
AUDIOBOOKS_DIR = "audiobooks"
PRESENTATIONS_DIR = "presentations"
PARAGRAPH_WAV = "paragraph.wav"
SAMPLE_WAV = "sample.wav"
CHECKPOINT_DIR = "checkpoint"
TRAIN_RAW_JSONL = "train_raw.jsonl"
TRAIN_WITH_CODES_JSONL = "train_with_codes.jsonl"
STORE_DB = "jobs.db"
STORE_SCHEMA_VERSION = "1"
_STORE_LOCK = threading.RLock()


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


def _presentations_dir() -> str:
    d = os.path.join(API_DATA_DIR, PRESENTATIONS_DIR)
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


def presentation_jobs_json_path() -> str:
    return os.path.join(_data_dir(), PRESENTATION_JOBS_JSON)


def audiobook_dir(job_id: str) -> str:
    d = os.path.join(_audiobooks_dir(), job_id)
    os.makedirs(d, exist_ok=True)
    return d


def voice_dir(voice_id: str) -> str:
    d = os.path.join(_voices_dir(), voice_id)
    os.makedirs(d, exist_ok=True)
    return d


def presentation_dir(job_id: str) -> str:
    d = os.path.join(_presentations_dir(), job_id)
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
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _store_db_path() -> str:
    return os.path.join(_data_dir(), STORE_DB)


def _connect_store() -> sqlite3.Connection:
    db = sqlite3.connect(_store_db_path(), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS records (
          store_name TEXT NOT NULL,
          record_id TEXT NOT NULL,
          position INTEGER NOT NULL,
          payload_json TEXT NOT NULL,
          updated_at REAL NOT NULL,
          PRIMARY KEY (store_name, record_id)
        );
        CREATE INDEX IF NOT EXISTS records_store_position_idx
          ON records(store_name, position);
        """
    )
    db.execute(
        "INSERT OR REPLACE INTO metadata(key,value) VALUES('schema_version',?)",
        (STORE_SCHEMA_VERSION,),
    )
    return db


def _migration_key(store_name: str) -> str:
    return f"json_imported:{store_name}"


def _backup_migrated_json(path: str) -> str:
    backup_path = f"{path}.migration-{int(time.time())}.bak"
    shutil.copy2(path, backup_path)
    os.chmod(backup_path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return backup_path


def _ensure_imported(db: sqlite3.Connection, store_name: str, json_path: str) -> None:
    key = _migration_key(store_name)
    if db.execute("SELECT 1 FROM metadata WHERE key=?", (key,)).fetchone():
        return
    records = _load_json_list(json_path)
    if os.path.exists(json_path):
        backup_path = _backup_migrated_json(json_path)
        print(f"Migrated {json_path} to SQLite; read-only backup: {backup_path}", flush=True)
    stamp = time.time()
    for position, record in enumerate(records):
        record_id = str(record.get("id") or f"legacy-{position}")
        db.execute(
            "INSERT OR REPLACE INTO records(store_name,record_id,position,payload_json,updated_at) VALUES(?,?,?,?,?)",
            (store_name, record_id, position, json.dumps(record, ensure_ascii=False), stamp),
        )
    db.execute("INSERT INTO metadata(key,value) VALUES(?,?)", (key, str(int(stamp))))


def _load_store(store_name: str, json_path: str) -> List[Dict[str, Any]]:
    with _STORE_LOCK, _connect_store() as db:
        _ensure_imported(db, store_name, json_path)
        rows = db.execute(
            "SELECT payload_json FROM records WHERE store_name=? ORDER BY position",
            (store_name,),
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]


def _save_store(store_name: str, json_path: str, records: List[Dict[str, Any]]) -> None:
    with _STORE_LOCK, _connect_store() as db:
        _ensure_imported(db, store_name, json_path)
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM records WHERE store_name=?", (store_name,))
        stamp = time.time()
        for position, record in enumerate(records):
            record_id = str(record.get("id") or f"legacy-{position}")
            db.execute(
                "INSERT INTO records(store_name,record_id,position,payload_json,updated_at) VALUES(?,?,?,?,?)",
                (store_name, record_id, position, json.dumps(record, ensure_ascii=False), stamp),
            )
        db.commit()


def _backup_json(path: str, reason: str) -> str:
    backup_path = f"{path}.corrupt-{int(time.time())}-{reason}"
    try:
        import shutil
        shutil.copy2(path, backup_path)
    except OSError:
        pass
    return backup_path


def _load_json_list(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, list) else []
    except json.JSONDecodeError as exc:
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
            value, end = json.JSONDecoder().raw_decode(raw)
        except (OSError, json.JSONDecodeError):
            backup_path = _backup_json(path, "unreadable")
            print(f"Warning: backed up unreadable JSON store {path} to {backup_path}")
            return []

        if isinstance(value, list):
            trailing = raw[end:].strip()
            backup_path = _backup_json(path, "trailing-data")
            _write_json_atomic(path, value)
            print(
                "Warning: repaired JSON store "
                f"{path}; backed up to {backup_path}; removed {len(trailing)} trailing chars"
            )
            return value

        backup_path = _backup_json(path, "not-list")
        print(f"Warning: backed up non-list JSON store {path} to {backup_path}: {exc}")
        return []


def slug_from_name(name: str) -> str:
    """Safe speaker_name for CustomVoice: alphanumeric and underscores only."""
    s = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip()).strip("_")
    return s.lower() if s else "speaker"


def load_voices() -> List[Dict[str, Any]]:
    return _load_store("voices", voices_json_path())


def save_voices(voices: List[Dict[str, Any]]) -> None:
    _save_store("voices", voices_json_path(), voices)


def load_models() -> List[Dict[str, Any]]:
    return _load_store("models", models_json_path())


def save_models(models: List[Dict[str, Any]]) -> None:
    _save_store("models", models_json_path(), models)


def load_voice_jobs() -> List[Dict[str, Any]]:
    return _load_store("voice_jobs", voice_jobs_json_path())


def save_voice_jobs(jobs: List[Dict[str, Any]]) -> None:
    _save_store("voice_jobs", voice_jobs_json_path(), jobs)


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
    return _load_store("synthesis_jobs", synthesis_jobs_json_path())


def save_synthesis_jobs(jobs: List[Dict[str, Any]]) -> None:
    _save_store("synthesis_jobs", synthesis_jobs_json_path(), jobs)


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
    return _load_store("audiobook_jobs", audiobook_jobs_json_path())


def save_audiobook_jobs(jobs: List[Dict[str, Any]]) -> None:
    _save_store("audiobook_jobs", audiobook_jobs_json_path(), jobs)


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


def load_presentation_jobs() -> List[Dict[str, Any]]:
    return _load_store("presentation_jobs", presentation_jobs_json_path())


def save_presentation_jobs(jobs: List[Dict[str, Any]]) -> None:
    _save_store("presentation_jobs", presentation_jobs_json_path(), jobs)


def get_presentation_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    for job in load_presentation_jobs():
        if job.get("id") == job_id:
            return job
    return None


def update_presentation_job(job_id: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
    jobs = load_presentation_jobs()
    for job in jobs:
        if job.get("id") == job_id:
            job.update(kwargs)
            save_presentation_jobs(jobs)
            return job
    return None


def update_presentation_slide(job_id: str, index: int, **kwargs: Any) -> Optional[Dict[str, Any]]:
    jobs = load_presentation_jobs()
    for job in jobs:
        if job.get("id") != job_id:
            continue
        for slide in job.get("slides", []):
            if int(slide.get("index", -1)) == int(index):
                slide.update(kwargs)
                processed = sum(1 for s in job.get("slides", []) if s.get("status") in ("completed", "empty", "flagged"))
                failed = sum(1 for s in job.get("slides", []) if s.get("status") == "failed")
                total = max(1, int(job.get("total_slides") or len(job.get("slides", [])) or 1))
                job["completed_slides"] = processed
                job["failed_slides"] = failed
                job["progress_percent"] = round((processed / total) * 100, 1)
                job["updated_at"] = kwargs.get("updated_at", job.get("updated_at"))
                save_presentation_jobs(jobs)
                return slide
    return None


def delete_presentation_job(job_id: str) -> Optional[Dict[str, Any]]:
    jobs = load_presentation_jobs()
    kept = []
    deleted = None
    for job in jobs:
        if job.get("id") == job_id:
            deleted = job
            continue
        kept.append(job)
    if deleted is not None:
        import shutil
        d = os.path.join(_presentations_dir(), job_id)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        save_presentation_jobs(kept)
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
