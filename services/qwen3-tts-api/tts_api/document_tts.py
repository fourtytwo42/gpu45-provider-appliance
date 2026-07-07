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
from tts_api.config import DEVICE
from tts_api.resource_guard import tts_vram_guard

SUPPORTED_EXTENSIONS = {".epub", ".pdf", ".docx", ".txt", ".md", ".html", ".htm"}
TARGET_CHUNK_CHARS = 450


CONTENT_START_RE = re.compile(
    r"(?im)^\s*(?:prologue|chapter\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten)\b|"
    r"epilogue|part\s+(?:\d+|[ivxlcdm]+)\b|volume\s+\d+\s+(?:prologue|chapter))"
)
SKIP_EPUB_DOC_RE = re.compile(
    r"(?i)(?:^|[/_-])(?:nav|toc|table[-_ ]?of[-_ ]?contents|contents|index|cover|titlepage|title[-_ ]?page|"
    r"copyright|credits|insert|newsletter|about[-_ ]?the[-_ ]?author|landmarks)(?:\.|[/_-]|$)"
)
TOC_HEADING_RE = re.compile(r"(?im)^\s*(?:table of contents|contents|index)\s*$")
DENSE_TOC_ENTRY_RE = re.compile(
    r"(?i)\b(?:prologue|chapter\s+(?:\d+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten)\b|"
    r"extra chapter|side story|epilogue|character design concept gallery|newsletter)"
)
DOWNLOAD_SPAM_RE = re.compile(r"(?i)(?:download\s+all|fav\s+light\s+novels|just\s+light\s+novels)")
VOLUME_RE = re.compile(r"(?i)\bvolume\s*[-_ ]*([0-9]+|[ivxlcdm]+)\b")


def utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _epub_item_text(item: Any) -> str:
    soup = BeautifulSoup(item.get_content(), "html.parser")
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    return normalize_text(soup.get_text("\n"))


def _looks_like_front_matter(name: str, text: str) -> bool:
    if SKIP_EPUB_DOC_RE.search(name or ""):
        return True
    if TOC_HEADING_RE.search(text[:2000]) and not CONTENT_START_RE.search(text[:4000]):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) >= 8:
        sample = lines[:30]
        short_lines = sum(1 for line in sample if len(line) <= 80)
        chapterish = sum(1 for line in sample if re.search(r"(?i)^(?:prologue|chapter|epilogue|side story|extra chapter|interlude)\b", line))
        if chapterish >= 4 and short_lines >= min(len(sample), 12):
            return True
    return False


def _strip_leading_front_matter(text: str) -> str:
    text = normalize_text(text)
    if not text:
        return ""
    head = text[:3000]
    dense_matches = list(DENSE_TOC_ENTRY_RE.finditer(head))
    if dense_matches and DOWNLOAD_SPAM_RE.search(text[:dense_matches[0].start()]):
        return text[dense_matches[0].start():].strip()
    if len(dense_matches) >= 4:
        # Some EPUBs place a plain text TOC at the front of the first content
        # document, then repeat Prologue/Chapter 1 where narration really starts.
        repeated_start = next((m for m in dense_matches[1:] if m.group(0).strip().lower().startswith("prologue")), None)
        if repeated_start is not None:
            return text[repeated_start.start():].strip()
    matches = list(CONTENT_START_RE.finditer(head))
    match = matches[0] if matches else CONTENT_START_RE.search(text)
    if not match:
        return text
    prefix = text[:match.start()]
    if TOC_HEADING_RE.search(prefix) or DOWNLOAD_SPAM_RE.search(prefix) or len(prefix) > 1200:
        return text[match.start():].strip()
    return text


def extract_epub_text(path: str) -> str:
    book = epub.read_epub(path)
    parts: list[str] = []
    started = False
    seen_ids: set[str] = set()
    ordered_items: list[Any] = []
    for entry in book.spine:
        item_id = entry[0] if isinstance(entry, tuple) else entry
        item = book.get_item_with_id(item_id)
        if item is not None:
            ordered_items.append(item)
            seen_ids.add(item.get_id())
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        if item.get_id() not in seen_ids:
            ordered_items.append(item)
    for item in ordered_items:
        if item.get_type() != ITEM_DOCUMENT:
            continue
        name = item.get_name() or ""
        text = _epub_item_text(item)
        if not text:
            continue
        if not started:
            stripped = _strip_leading_front_matter(text)
            if _looks_like_front_matter(name, text) and stripped == text:
                continue
            text = stripped
            if not text:
                continue
            started = True
        parts.append(text)
    return "\n\n".join(parts).strip()


def audiobook_intro_text(title: str, source_filename: str) -> str:
    base = (title or Path(source_filename).stem or "Audiobook").strip()
    base = re.sub(r"[_]+", " ", base)
    base = re.sub(r"\s+-\s+", ", ", base)
    base = re.sub(r"\s+", " ", base).strip()
    volume_match = VOLUME_RE.search(base)
    if volume_match:
        raw_volume = volume_match.group(1)
        volume = raw_volume.upper() if raw_volume.lower() in {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"} else raw_volume
        title_text = VOLUME_RE.sub("", base).strip(" ,-_")
        return f"{title_text}. Volume {volume}." if title_text else f"Volume {volume}."
    return f"{base}."


def extract_text(path: str, filename: str | None = None) -> str:
    ext = Path(filename or path).suffix.lower()
    if ext == ".pdf":
        reader = PdfReader(path)
        return _strip_leading_front_matter("\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip())
    if ext == ".docx":
        doc = Document(path)
        return _strip_leading_front_matter("\n\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip()).strip())
    if ext == ".epub":
        return extract_epub_text(path)
    if ext in (".html", ".htm"):
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        return _strip_leading_front_matter(normalize_text(soup.get_text("\n")))
    return _strip_leading_front_matter(normalize_text(Path(path).read_text(encoding="utf-8", errors="ignore")))


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
    text = re.sub(
        r"\s+(?=(?:Prologue|Epilogue|Extra Chapter|Side Story:|Chapter\s+\d+:|Character Design Concept Gallery|About the Author|Newsletter)\b)",
        "\n",
        text,
    )
    sentence_pattern = re.compile(r".+?(?:[.!?][\"')\]]*|$)(?=\s+|$)", re.DOTALL)
    sentences: list[str] = []
    for paragraph in re.split(r"\n\s*\n+", text):
        for line in paragraph.splitlines():
            line = re.sub(r"\s+", " ", line).strip()
            if not line:
                continue
            if len(line) <= 140 and not re.search(r"[.!?][\"')\]]*$", line):
                sentences.append(line)
                continue
            matches = [match.group(0).strip() for match in sentence_pattern.finditer(line) if match.group(0).strip()]
            sentences.extend(matches or [line])
    return sentences


def split_text(text: str, target_chars: int = TARGET_CHUNK_CHARS) -> list[str]:
    target_chars = max(240, min(int(target_chars or TARGET_CHUNK_CHARS), 1200))
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
    text = _strip_leading_front_matter(text)
    chunks_text = split_text(text)
    if not chunks_text:
        raise ValueError("No synthesizable chunks were created")
    intro_text = audiobook_intro_text((title or Path(source_filename).stem or "Audiobook").strip(), source_filename)
    chunks_text = [intro_text, *chunks_text]
    job_id = store.generate_id()
    os.makedirs(os.path.join(store.audiobook_dir(job_id), "chunks"), exist_ok=True)
    chunks = [
        {
            "index": i,
            "status": "pending",
            "role": "intro" if i == 0 else "content",
            "pause_after_ms": 1000 if i == 0 else 500,
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
        "front_matter_policy": "skip_index_start_at_first_section",
        "intro_text": intro_text,
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


def pause_for_resource(job_id: str, reason: str = "GPU resource handoff") -> dict[str, Any]:
    job = reset_interrupted_chunks(job_id)
    if job.get("status") not in ("queued", "running", "pausing"):
        return job
    out = stitch_completed_chunks(job_id)
    return store.update_audiobook_job(
        job_id,
        status="paused",
        paused_by_resource=True,
        pause_reason=reason,
        progress_label=f"Paused: {reason}",
        current_chunk=None,
        stop_requested=False,
        stitched_output_path=out or job.get("stitched_output_path"),
        updated_at=utcnow(),
    ) or job


def pause_active_audiobooks(reason: str = "GPU resource handoff") -> list[dict[str, Any]]:
    paused: list[dict[str, Any]] = []
    for job in store.load_audiobook_jobs():
        if job.get("status") in ("queued", "running", "pausing"):
            paused.append(pause_for_resource(str(job["id"]), reason))
    return paused


def prepare_resume(job_id: str) -> dict[str, Any]:
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        raise KeyError("Audiobook job not found")
    if job.get("status") != "paused":
        return job
    reset_interrupted_chunks(job_id)
    return store.update_audiobook_job(
        job_id,
        status="queued",
        paused_by_resource=False,
        pause_reason=None,
        stop_requested=False,
        progress_label="Queued for resume",
        updated_at=utcnow(),
    ) or job


def reset_interrupted_chunks(job_id: str) -> dict[str, Any]:
    jobs = store.load_audiobook_jobs()
    for job in jobs:
        if job.get("id") != job_id:
            continue
        changed = False
        for chunk in job.get("chunks", []):
            if chunk.get("status") == "running":
                chunk["status"] = "pending"
                chunk.pop("started_at", None)
                chunk["updated_at"] = utcnow()
                changed = True
        if changed:
            completed = sum(1 for c in job.get("chunks", []) if c.get("status") == "completed")
            failed = sum(1 for c in job.get("chunks", []) if c.get("status") == "failed")
            total = max(1, int(job.get("total_chunks") or len(job.get("chunks", [])) or 1))
            job.update(
                completed_chunks=completed,
                failed_chunks=failed,
                current_chunk=None,
                progress_percent=round((completed / total) * 100, 1),
                updated_at=utcnow(),
            )
            store.save_audiobook_jobs(jobs)
        return job
    raise KeyError("Audiobook job not found")


def stitch_completed_chunks(job_id: str) -> str | None:
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        return None
    audio = AudioSegment.empty()
    added = 0
    for chunk in job.get("chunks", []):
        if chunk.get("status") != "completed":
            continue
        path = chunk.get("output_path")
        if not path or not os.path.exists(path):
            continue
        if added > 0:
            previous = job.get("chunks", [])[added - 1] if added - 1 < len(job.get("chunks", [])) else {}
            pause_ms = int(previous.get("pause_after_ms") or 500)
            audio += AudioSegment.silent(duration=max(0, pause_ms))
        audio += AudioSegment.from_file(path, format="mp3")
        added += 1
    if added == 0:
        return None
    out = _stitched_audio_path(job_id)
    audio.export(out, format="mp3")
    store.update_audiobook_job(job_id, stitched_output_path=out, stitched_completed_chunks=added, stitched_at=utcnow(), updated_at=utcnow())
    return out


def run_audiobook_job(job_id: str) -> None:
    started = monotonic()
    job = store.get_audiobook_job_by_id(job_id)
    if not job:
        return
    with tts_vram_guard("audiobook", device=DEVICE):
        try:
            _run_audiobook_job_inner(job_id, started, job)
        finally:
            synthesize_module.unload_cached_models()


def _run_audiobook_job_inner(job_id: str, started: float, job: dict[str, Any]) -> None:
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
