from __future__ import annotations

import io
import os
import re
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

import numpy as np
import soundfile as sf
from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_DOCUMENT
from docx import Document
from pydub import AudioSegment
from pypdf import PdfReader

from tts_api import store
from tts_api.audio_convert import wav_to_mp3_bytes
from tts_api import synthesize as synthesize_module

SUPPORTED_EXTENSIONS = {".epub", ".pdf", ".docx", ".txt", ".md", ".html", ".htm"}
TARGET_CHUNK_CHARS = 900


def utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def extract_text(path: str, filename: str | None = None) -> str:
    ext = Path(filename or path).suffix.lower()
    if ext == ".pdf":
        reader = PdfReader(path)
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    if ext == ".docx":
        doc = Document(path)
        return "\n\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip()).strip()
    if ext == ".epub":
        book = epub.read_epub(path)
        parts: list[str] = []
        for item in book.get_items_of_type(ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            for tag in soup(["script", "style", "nav"]):
                tag.decompose()
            text = soup.get_text("\n")
            text = normalize_text(text)
            if text:
                parts.append(text)
        return "\n\n".join(parts).strip()
    if ext in (".html", ".htm"):
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        return normalize_text(soup.get_text("\n"))
    return normalize_text(Path(path).read_text(encoding="utf-8", errors="ignore"))


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^\s*Page\s+\d+\s*$", "", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    sentence_pattern = re.compile(r".+?(?:[.!?][\"')\]]*|$)(?=\s+|$)", re.DOTALL)
    sentences: list[str] = []
    for paragraph in re.split(r"\n\s*\n+", text):
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if not paragraph:
            continue
        matches = [match.group(0).strip() for match in sentence_pattern.finditer(paragraph) if match.group(0).strip()]
        sentences.extend(matches or [paragraph])
    return sentences


def split_text(text: str, target_chars: int = TARGET_CHUNK_CHARS) -> list[str]:
    target_chars = max(500, min(int(target_chars or TARGET_CHUNK_CHARS), 1600))
    chunks: list[str] = []
    current = ""
    for sentence in split_sentences(text):
        if not current:
            current = sentence
            continue
        if len(current) + 1 + len(sentence) <= target_chars:
            current = f"{current} {sentence}"
        else:
            chunks.append(current.strip())
            current = sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks


def analyze_wav_quality(wav_bytes: bytes, sample_rate: int, text: str) -> dict[str, Any]:
    try:
        samples, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        if samples.ndim > 1:
            mono = samples.mean(axis=1)
        else:
            mono = samples
        duration = float(len(mono) / float(sr or sample_rate or 1))
        rms = float(np.sqrt(np.mean(np.square(mono)))) if len(mono) else 0.0
        peak = float(np.max(np.abs(mono))) if len(mono) else 0.0
        signs = np.signbit(mono)
        zcr = float(np.mean(signs[1:] != signs[:-1])) if len(mono) > 1 else 0.0
        reasons: list[str] = []
        if duration < 0.35:
            reasons.append("too_short")
        if len(text) > 80 and duration < 2.0:
            reasons.append("too_short_for_text")
        if rms < 0.0015 or peak < 0.01:
            reasons.append("near_silence")
        if zcr > 0.38 and rms > 0.02:
            reasons.append("high_zero_crossing_noise")
        return {
            "ok": len(reasons) == 0,
            "reasons": reasons,
            "duration_seconds": round(duration, 3),
            "rms": round(rms, 6),
            "peak": round(peak, 6),
            "zero_crossing_rate": round(zcr, 6),
        }
    except Exception as exc:
        return {"ok": False, "reasons": [f"quality_check_failed:{exc}"], "duration_seconds": 0.0}


def _chunk_audio_path(job_id: str, index: int) -> str:
    return os.path.join(store.audiobook_dir(job_id), "chunks", f"chunk_{index:05d}.mp3")


def _stitched_audio_path(job_id: str) -> str:
    return os.path.join(store.audiobook_dir(job_id), f"audiobook_{job_id}.mp3")


def create_audiobook_job(source_path: str, source_filename: str, model_id: str, title: str | None) -> dict[str, Any]:
    model = store.get_model_by_id(model_id)
    if not model:
        raise KeyError(f"Model not found: {model_id}")
    if model.get("status") != "ready":
        raise ValueError("Model is not ready")
    text = extract_text(source_path, source_filename)
    if not text:
        raise ValueError("No readable text found in uploaded document")
    chunks_text = split_text(text)
    if not chunks_text:
        raise ValueError("No synthesizable chunks were created")
    job_id = store.generate_id()
    os.makedirs(os.path.join(store.audiobook_dir(job_id), "chunks"), exist_ok=True)
    chunks = [
        {
            "index": i,
            "status": "pending",
            "text": chunk,
            "text_chars": len(chunk),
            "output_path": _chunk_audio_path(job_id, i),
            "audio_url": f"/audiobooks/{job_id}/chunks/{i}/audio",
            "quality": None,
        }
        for i, chunk in enumerate(chunks_text)
    ]
    job = {
        "id": job_id,
        "kind": "audiobook",
        "status": "queued",
        "title": (title or Path(source_filename).stem or "Audiobook").strip(),
        "source_filename": source_filename,
        "model_id": model_id,
        "model_name": model.get("name"),
        "split_strategy": "sentence",
        "target_chunk_chars": TARGET_CHUNK_CHARS,
        "total_chunks": len(chunks),
        "completed_chunks": 0,
        "failed_chunks": 0,
        "current_chunk": None,
        "progress_percent": 0.0,
        "progress_label": "Queued",
        "stop_requested": False,
        "stitched_output_path": _stitched_audio_path(job_id),
        "stitched_audio_url": f"/audiobooks/{job_id}/audio",
        "text_chars": len(text),
        "chunks": chunks,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    jobs = store.load_audiobook_jobs()
    jobs.append(job)
    store.save_audiobook_jobs(jobs)
    return job


def request_stop(job_id: str) -> dict[str, Any]:
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        raise KeyError("Audiobook job not found")
    if job.get("status") not in ("queued", "running"):
        return job
    return store.update_audiobook_job(job_id, stop_requested=True, progress_label="Stop requested", updated_at=utcnow()) or job


def stitch_completed_chunks(job_id: str) -> str | None:
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        return None
    audio = AudioSegment.empty()
    silence = AudioSegment.silent(duration=500)
    added = 0
    for chunk in job.get("chunks", []):
        if chunk.get("status") != "completed":
            continue
        path = chunk.get("output_path")
        if not path or not os.path.exists(path):
            continue
        if added > 0:
            audio += silence
        audio += AudioSegment.from_file(path, format="mp3")
        added += 1
    if added == 0:
        return None
    out = _stitched_audio_path(job_id)
    audio.export(out, format="mp3")
    return out


def run_audiobook_job(job_id: str) -> None:
    started = monotonic()
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        return
    try:
        store.update_audiobook_job(job_id, status="running", progress_label="Starting", started_at=job.get("started_at") or utcnow(), stop_requested=False, updated_at=utcnow())
        while True:
            job = store.get_audiobook_job_by_id(job_id)
            if not job:
                return
            if job.get("stop_requested"):
                out = stitch_completed_chunks(job_id)
                store.update_audiobook_job(job_id, status="stopped", progress_label="Stopped", stitched_output_path=out or job.get("stitched_output_path"), updated_at=utcnow())
                return
            chunks = job.get("chunks", [])
            next_chunk = next((c for c in chunks if c.get("status") in ("pending", "failed")), None)
            if not next_chunk:
                out = stitch_completed_chunks(job_id)
                elapsed = monotonic() - started
                store.update_audiobook_job(
                    job_id,
                    status="completed",
                    progress_label="Complete",
                    progress_percent=100.0,
                    current_chunk=None,
                    stitched_output_path=out or job.get("stitched_output_path"),
                    elapsed_seconds=round(elapsed, 1),
                    finished_at=utcnow(),
                    updated_at=utcnow(),
                )
                return
            idx = int(next_chunk["index"])
            store.update_audiobook_chunk(job_id, idx, status="running", started_at=utcnow(), updated_at=utcnow())
            completed = sum(1 for c in chunks if c.get("status") == "completed")
            total = max(1, int(job.get("total_chunks") or len(chunks) or 1))
            store.update_audiobook_job(
                job_id,
                status="running",
                current_chunk=idx,
                completed_chunks=completed,
                failed_chunks=sum(1 for c in chunks if c.get("status") == "failed"),
                progress_percent=round((completed / total) * 100, 1),
                progress_label=f"Generating chunk {idx + 1} of {total}",
                elapsed_seconds=round(monotonic() - started, 1),
                updated_at=utcnow(),
            )
            try:
                wav_bytes, sr = synthesize_module.synthesize(text=next_chunk["text"], model_id=job["model_id"])
                quality = analyze_wav_quality(wav_bytes, sr, next_chunk["text"])
                mp3_bytes = wav_to_mp3_bytes(wav_bytes)
                output_path = _chunk_audio_path(job_id, idx)
                with open(output_path, "wb") as f:
                    f.write(mp3_bytes)
                status = "completed" if quality.get("ok") else "flagged"
                store.update_audiobook_chunk(
                    job_id,
                    idx,
                    status=status,
                    output_path=output_path,
                    output_bytes=len(mp3_bytes),
                    quality=quality,
                    finished_at=utcnow(),
                    updated_at=utcnow(),
                )
                if status == "flagged":
                    store.update_audiobook_job(job_id, status="needs_review", progress_label=f"Chunk {idx + 1} flagged: {', '.join(quality.get('reasons', []))}", updated_at=utcnow())
                    return
            except Exception as exc:
                store.update_audiobook_chunk(job_id, idx, status="failed", error=str(exc), finished_at=utcnow(), updated_at=utcnow())
                store.update_audiobook_job(job_id, status="failed", error=str(exc), progress_label="Failed", updated_at=utcnow())
                return
    except Exception as exc:
        store.update_audiobook_job(job_id, status="failed", error=str(exc), progress_label="Failed", updated_at=utcnow())
