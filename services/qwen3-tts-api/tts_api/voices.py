"""
Create voices from prompts using VoiceDesign and fixed paragraph text.
"""
import os
import re
import shutil
import subprocess
import threading
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import requests
import torch
import soundfile as sf

from qwen_tts import Qwen3TTSModel

from tts_api.config import DEVICE, IMPORT_MAX_SECONDS, VOICE_DESIGN_MODEL, WHISPER_API_URL
from tts_api.constants import VOICE_PARAGRAPH_TEXT
from tts_api import store
from tts_api.resource_guard import tts_vram_guard


def create_voice(
    instruct: str,
    language: str = "English",
    name: Optional[str] = None,
    device: Optional[str] = None,
    progress: Optional[Callable[[str, float, Optional[float]], None]] = None,
) -> Dict[str, Any]:
    """
    Generate paragraph audio with VoiceDesign and save as a named voice.
    Returns voice record with id, name, instruct, language, paragraph_path, created_at.
    """
    voice_id = store.generate_id()
    voice_name = (name or "").strip() or store.default_voice_name(voice_id)
    voices = store.load_voices()
    if store.get_voice_by_name(voice_name):
        raise ValueError(f"Voice name already exists: {voice_name}")

    paragraph_path = store.voice_paragraph_path(voice_id)
    os.makedirs(store.voice_dir(voice_id), exist_ok=True)

    target_device = (device or DEVICE or "cpu").strip()
    expected_seconds = 180.0 if target_device != "cpu" else 900.0
    stop_progress = threading.Event()

    def set_progress(label: str, percent: float, eta_seconds: Optional[float] = None) -> None:
        if progress:
            progress(label, percent, eta_seconds)

    def estimate_generation_progress() -> None:
        started = time.monotonic()
        while not stop_progress.wait(2):
            elapsed = time.monotonic() - started
            fraction = min(1.0, elapsed / expected_seconds)
            eta = max(0.0, expected_seconds - elapsed)
            set_progress("Generating reference voice", min(94.0, 20.0 + (fraction * 74.0)), eta)

    set_progress("Loading VoiceDesign model", 10.0, expected_seconds)
    guard = tts_vram_guard("create_voice", device=target_device) if target_device != "cpu" else nullcontext()
    with guard:
        model = Qwen3TTSModel.from_pretrained(
            VOICE_DESIGN_MODEL,
            device_map=target_device,
            dtype=torch.bfloat16,
        )
        monitor = threading.Thread(target=estimate_generation_progress, daemon=True)
        monitor.start()
        try:
            wavs, sr = model.generate_voice_design(
                text=VOICE_PARAGRAPH_TEXT,
                instruct=instruct or "",
                language=language or "English",
            )
        finally:
            stop_progress.set()
            del model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    set_progress("Saving voice sample", 95.0, 0.0)
    sf.write(paragraph_path, wavs[0], sr)

    voice = {
        "id": voice_id,
        "name": voice_name,
        "instruct": instruct or "",
        "language": language or "English",
        "device": target_device,
        "paragraph_text": VOICE_PARAGRAPH_TEXT,
        "paragraph_path": paragraph_path,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    voices.append(voice)
    store.save_voices(voices)
    set_progress("Complete", 100.0, 0.0)
    return voice


def _extract_transcript(markdown: str) -> str:
    chunks = []
    in_transcript = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped == "## Transcript":
            in_transcript = True
            continue
        if stripped.startswith("## ") and in_transcript:
            break
        if not in_transcript or not stripped:
            continue
        match = re.match(r"\*\*\[[^\]]+\]\*\*\s*(.*)", stripped) or re.match(r"- \[[^\]]+\]\s*(.*)", stripped)
        text = match.group(1).strip() if match else stripped
        if text:
            chunks.append(text)
    return " ".join(chunks).strip()


def _transcribe_audio(audio_path: str, language: str, progress: Optional[Callable[[str, float, Optional[float]], None]]) -> str:
    if progress:
        progress("Transcribing reference audio", 45.0, 90.0)
    with open(audio_path, "rb") as f:
        response = requests.post(
            f"{WHISPER_API_URL.rstrip('/')}/jobs",
            files={"file": (Path(audio_path).name, f, "audio/wav")},
            data={"model": "base", "task": "transcribe", "language": (language or "en")[:2].lower()},
            timeout=60,
        )
    response.raise_for_status()
    job_id = response.json()["id"]
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        jobs_response = requests.get(f"{WHISPER_API_URL.rstrip('/')}/jobs", timeout=30)
        jobs_response.raise_for_status()
        job = next((item for item in jobs_response.json() if item.get("id") == job_id), None)
        if job:
            if progress:
                progress(
                    job.get("progress_label") or "Transcribing reference audio",
                    45.0 + min(35.0, float(job.get("progress_percent") or 0) * 0.35),
                    job.get("eta_seconds"),
                )
            if job.get("status") == "completed":
                transcript_response = requests.get(f"{WHISPER_API_URL.rstrip('/')}/jobs/{job_id}/transcript", timeout=60)
                transcript_response.raise_for_status()
                transcript = _extract_transcript(transcript_response.text)
                if transcript:
                    return transcript
                raise RuntimeError("Whisper completed but no transcript text was recovered.")
            if job.get("status") == "failed":
                raise RuntimeError(job.get("error") or "Whisper transcription failed.")
        time.sleep(2)
    raise TimeoutError("Timed out waiting for Whisper transcription.")


def import_voice_from_media(
    source_path: str,
    source_filename: str,
    name: str,
    language: str = "English",
    transcript: Optional[str] = None,
    progress: Optional[Callable[[str, float, Optional[float]], None]] = None,
) -> Dict[str, Any]:
    voice_name = (name or "").strip()
    if not voice_name:
        raise ValueError("Voice name is required")
    if store.get_voice_by_name(voice_name):
        raise ValueError(f"Voice name already exists: {voice_name}")

    voice_id = store.generate_id()
    voice_dir = store.voice_dir(voice_id)
    paragraph_path = store.voice_paragraph_path(voice_id)
    source_ext = Path(source_filename or source_path).suffix or ".media"
    saved_source_path = os.path.join(voice_dir, f"source{source_ext}")
    shutil.copyfile(source_path, saved_source_path)

    def set_progress(label: str, percent: float, eta_seconds: Optional[float] = None) -> None:
        if progress:
            progress(label, percent, eta_seconds)

    set_progress("Extracting reference audio", 15.0, 30.0)
    ffmpeg_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        saved_source_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-t",
        str(max(5, IMPORT_MAX_SECONDS)),
        paragraph_path,
    ]
    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to extract voice audio: {result.stderr or result.stdout}")

    paragraph_text = (transcript or "").strip()
    transcript_source = "submitted"
    if not paragraph_text:
        paragraph_text = _transcribe_audio(paragraph_path, language, progress)
        transcript_source = "whisper"
    if len(paragraph_text) < 8:
        raise ValueError("Transcript is too short for voice training.")

    set_progress("Saving imported voice", 95.0, 0.0)
    voice = {
        "id": voice_id,
        "name": voice_name,
        "instruct": f"Imported from {source_filename}",
        "language": language or "English",
        "device": "import",
        "source": "upload",
        "source_filename": source_filename,
        "source_path": saved_source_path,
        "paragraph_text": paragraph_text,
        "transcript_source": transcript_source,
        "paragraph_path": paragraph_path,
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    voices = store.load_voices()
    voices.append(voice)
    store.save_voices(voices)
    set_progress("Complete", 100.0, 0.0)
    return voice


def rename_voice(voice_id: str, name: str) -> Dict[str, Any]:
    """Rename a voice. Enforces unique name."""
    voices = store.load_voices()
    name = (name or "").strip()
    if not name:
        raise ValueError("Name cannot be empty")
    existing = store.get_voice_by_name(name)
    if existing and existing.get("id") != voice_id:
        raise ValueError(f"Voice name already exists: {name}")
    for v in voices:
        if v.get("id") == voice_id:
            v["name"] = name
            store.save_voices(voices)
            return v
    raise KeyError(f"Voice not found: {voice_id}")


def delete_voice(voice_id: str) -> None:
    """Remove voice metadata and voice files."""
    voices = store.load_voices()
    kept = []
    for v in voices:
        if v.get("id") == voice_id:
            dir_path = store.voice_dir(voice_id)
            if os.path.isdir(dir_path):
                try:
                    shutil.rmtree(dir_path)
                except OSError:
                    pass
            continue
        kept.append(v)
    if len(kept) == len(voices):
        raise KeyError(f"Voice not found: {voice_id}")
    store.save_voices(kept)
