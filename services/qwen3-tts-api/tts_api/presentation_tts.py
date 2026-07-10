from __future__ import annotations

import os
import posixpath
import re
import shutil
import zipfile
import base64
from datetime import datetime
from io import BytesIO
from pathlib import Path
from time import monotonic
from typing import Any
from xml.etree import ElementTree as ET

from pydub import AudioSegment

from tts_api import store
from tts_api.audio_convert import wav_to_mp3_bytes
from tts_api.config import DEVICE
from tts_api import synthesize as synthesize_module
from tts_api.document_tts import TARGET_CHUNK_CHARS, analyze_wav_quality, split_text
from tts_api.resource_guard import tts_vram_guard

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "p14": "http://schemas.microsoft.com/office/powerpoint/2010/main",
}

for prefix in ("a", "p", "r", "p14"):
    ET.register_namespace(prefix, NS[prefix])

CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
MEDIA_REL_TYPE = "http://schemas.microsoft.com/office/2007/relationships/media"
AUDIO_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/audio"
IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
NOTES_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
PRESENTATION_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
MP3_CONTENT_TYPE = "audio/mpeg"
EMPTY_SLIDE_ADVANCE_MS = 1500
NARRATION_MEDIA_GUARD_MS = 500
NARRATION_ADVANCE_PAD_MS = 500
AUDIO_PLACEHOLDER_NAME = "ppt/media/narration_audio_placeholder.png"
AUDIO_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnR6tsAAAAASUVORK5CYII="
)


def qn(prefix: str, name: str) -> str:
    return f"{{{NS[prefix]}}}{name}"


def utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def rels_path_for(part_path: str) -> str:
    directory, filename = posixpath.split(part_path)
    return posixpath.join(directory, "_rels", f"{filename}.rels")


def normalize_part_path(base_part: str, target: str) -> str:
    base_dir = posixpath.dirname(base_part)
    return posixpath.normpath(posixpath.join(base_dir, target)).lstrip("/")


def parse_xml(raw: bytes) -> ET.Element:
    return ET.fromstring(raw)


def xml_bytes(root: ET.Element) -> bytes:
    if root.tag == f"{{{CONTENT_TYPES_NS}}}Types":
        ET.register_namespace("", CONTENT_TYPES_NS)
    elif root.tag == qn("rel", "Relationships"):
        ET.register_namespace("", NS["rel"])
    else:
        for prefix in ("a", "p", "r", "p14"):
            ET.register_namespace(prefix, NS[prefix])
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def validate_pptx(path: str) -> None:
    """Reject malformed packages before they become downloadable artifacts."""
    with zipfile.ZipFile(path, "r") as zf:
        bad_entry = zf.testzip()
        if bad_entry is not None:
            raise ValueError(f"Generated PPTX contains a corrupt ZIP entry: {bad_entry}")

        names = set(zf.namelist())
        content_types_raw = zf.read("[Content_Types].xml")
        canonical_types_root = f'<Types xmlns="{CONTENT_TYPES_NS}"'.encode("utf-8")
        if canonical_types_root not in content_types_raw:
            raise ValueError("Generated PPTX does not use the canonical unprefixed Types root")
        for name in names:
            if not (name.endswith(".xml") or name.endswith(".rels")):
                continue
            raw = zf.read(name)
            try:
                parse_xml(raw)
            except ET.ParseError as exc:
                raise ValueError(f"Generated PPTX contains invalid XML in {name}: {exc}") from exc
            if b'r:embed=""' in raw or b'r:link=""' in raw:
                raise ValueError(f"Generated PPTX contains an empty relationship attribute in {name}")

        for rels_path in sorted(names):
            if not re.fullmatch(r"ppt/slides/_rels/slide\d+\.xml\.rels", rels_path):
                continue
            rels = parse_xml(zf.read(rels_path))
            rels_dir, rels_filename = posixpath.split(rels_path)
            source_part = posixpath.join(
                posixpath.dirname(rels_dir),
                rels_filename.removesuffix(".rels"),
            )
            for relationship in _relationship_items(rels):
                target = relationship.attrib.get("Target", "")
                if not target:
                    raise ValueError(f"Generated PPTX relationship has no target in {rels_path}")
                if relationship.attrib.get("TargetMode") == "External" or "://" in target:
                    continue
                target_part = normalize_part_path(source_part, target)
                if target_part not in names:
                    raise ValueError(f"Generated PPTX relationship target is missing: {rels_path} -> {target}")


def _presentation_dir(job_id: str) -> str:
    return store.presentation_dir(job_id)


def _source_path(job_id: str) -> str:
    return os.path.join(_presentation_dir(job_id), "source.pptx")


def _output_path(job_id: str) -> str:
    return os.path.join(_presentation_dir(job_id), f"narrated_{job_id}.pptx")


def _slide_audio_path(job_id: str, index: int) -> str:
    return os.path.join(_presentation_dir(job_id), "slides", f"slide_{index + 1:05d}.mp3")


def _chunk_audio_path(job_id: str, slide_index: int, chunk_index: int) -> str:
    return os.path.join(_presentation_dir(job_id), "chunks", f"slide_{slide_index + 1:05d}_chunk_{chunk_index + 1:03d}.mp3")


def _load_relationships(zf: zipfile.ZipFile, rels_path: str) -> ET.Element:
    if rels_path in zf.namelist():
        return parse_xml(zf.read(rels_path))
    return ET.Element(qn("rel", "Relationships"))


def _relationship_items(root: ET.Element) -> list[ET.Element]:
    return list(root.findall(qn("rel", "Relationship")))


def _next_rel_id(root: ET.Element) -> str:
    max_id = 0
    for rel in _relationship_items(root):
        rid = rel.attrib.get("Id", "")
        match = re.match(r"rId(\d+)$", rid)
        if match:
            max_id = max(max_id, int(match.group(1)))
    return f"rId{max_id + 1}"


def _slide_order(zf: zipfile.ZipFile) -> list[str]:
    presentation = parse_xml(zf.read("ppt/presentation.xml"))
    rels = _load_relationships(zf, "ppt/_rels/presentation.xml.rels")
    rel_by_id = {rel.attrib.get("Id"): rel for rel in _relationship_items(rels)}
    slide_paths: list[str] = []
    for slide_id in presentation.findall(".//p:sldId", NS):
        rid = slide_id.attrib.get(qn("r", "id"))
        rel = rel_by_id.get(rid)
        if rel is None or rel.attrib.get("Type") != PRESENTATION_REL_TYPE:
            continue
        slide_paths.append(normalize_part_path("ppt/presentation.xml", rel.attrib.get("Target", "")))
    return slide_paths


def _notes_path_for_slide(zf: zipfile.ZipFile, slide_path: str) -> str | None:
    rels_path = rels_path_for(slide_path)
    if rels_path not in zf.namelist():
        return None
    rels = _load_relationships(zf, rels_path)
    for rel in _relationship_items(rels):
        if rel.attrib.get("Type") == NOTES_REL_TYPE:
            return normalize_part_path(slide_path, rel.attrib.get("Target", ""))
    return None


def _shape_text(shape: ET.Element) -> str:
    texts = [node.text or "" for node in shape.findall(".//a:t", NS)]
    return " ".join(text.strip() for text in texts if text and text.strip()).strip()


def _extract_notes_text(zf: zipfile.ZipFile, notes_path: str | None) -> str:
    if not notes_path or notes_path not in zf.namelist():
        return ""
    root = parse_xml(zf.read(notes_path))
    body_parts: list[str] = []
    fallback_parts: list[str] = []
    for shape in root.findall(".//p:sp", NS):
        text = _shape_text(shape)
        if not text:
            continue
        fallback_parts.append(text)
        ph = shape.find(".//p:nvPr/p:ph", NS)
        if ph is not None and ph.attrib.get("type") == "body":
            body_parts.append(text)
    parts = body_parts or fallback_parts
    return re.sub(r"\s+", " ", "\n\n".join(parts)).strip()


def inspect_pptx(path: str) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if "ppt/presentation.xml" not in zf.namelist():
                raise ValueError("Uploaded file is not a readable .pptx presentation.")
            slides = []
            for index, slide_path in enumerate(_slide_order(zf)):
                notes_path = _notes_path_for_slide(zf, slide_path)
                notes = _extract_notes_text(zf, notes_path)
                slides.append({
                    "index": index,
                    "slide_number": index + 1,
                    "slide_path": slide_path,
                    "notes_path": notes_path,
                    "text": notes,
                    "text_chars": len(notes),
                })
            if not slides:
                raise ValueError("No slides were found in the uploaded .pptx.")
            return slides
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded file is not a valid .pptx archive.") from exc


def create_presentation_job(source_path: str, source_filename: str, model_id: str, title: str | None) -> dict[str, Any]:
    ext = Path(source_filename or source_path).suffix.lower()
    if ext == ".ppt":
        raise ValueError("Legacy .ppt files are not supported. Save the presentation as .pptx and upload again.")
    if ext != ".pptx":
        raise ValueError("Only .pptx files are supported for narrated presentations.")
    model = store.get_model_by_id(model_id)
    if not model:
        raise KeyError(f"Model not found: {model_id}")
    if model.get("status") != "ready":
        raise ValueError("Model is not ready")
    inspected = inspect_pptx(source_path)
    job_id = store.generate_id()
    os.makedirs(os.path.join(_presentation_dir(job_id), "slides"), exist_ok=True)
    os.makedirs(os.path.join(_presentation_dir(job_id), "chunks"), exist_ok=True)
    shutil.copy2(source_path, _source_path(job_id))
    slides = []
    for slide in inspected:
        has_text = bool((slide.get("text") or "").strip())
        index = int(slide["index"])
        slides.append({
            **slide,
            "status": "pending" if has_text else "empty",
            "output_path": _slide_audio_path(job_id, index),
            "audio_url": f"/presentations/{job_id}/slides/{index}/audio",
            "quality": None,
        })
    processed = sum(1 for slide in slides if slide.get("status") == "empty")
    total = max(1, len(slides))
    job = {
        "id": job_id,
        "kind": "presentation",
        "status": "queued",
        "title": (title or Path(source_filename).stem or "Narrated presentation").strip(),
        "source_filename": source_filename,
        "model_id": model_id,
        "model_name": model.get("name"),
        "total_slides": len(slides),
        "narration_slides": sum(1 for slide in slides if slide.get("status") == "pending"),
        "completed_slides": processed,
        "failed_slides": 0,
        "current_slide": None,
        "progress_percent": round((processed / total) * 100, 1),
        "progress_label": "Queued",
        "stop_requested": False,
        "source_path": _source_path(job_id),
        "output_path": _output_path(job_id),
        "output_url": f"/presentations/{job_id}/output",
        "slides": slides,
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    jobs = store.load_presentation_jobs()
    jobs.append(job)
    store.save_presentation_jobs(jobs)
    return job


def request_stop(job_id: str) -> dict[str, Any]:
    job = store.get_presentation_job_by_id(job_id)
    if not job:
        raise KeyError("Presentation job not found")
    if job.get("status") not in ("queued", "running"):
        return job
    if job.get("status") == "queued":
        return store.update_presentation_job(
            job_id,
            status="stopped",
            stop_requested=True,
            progress_label="Stopped before processing",
            updated_at=utcnow(),
        ) or job
    return store.update_presentation_job(job_id, stop_requested=True, progress_label="Stop requested", updated_at=utcnow()) or job


def reset_interrupted_slides(job_id: str) -> dict[str, Any]:
    jobs = store.load_presentation_jobs()
    for job in jobs:
        if job.get("id") != job_id:
            continue
        changed = False
        for slide in job.get("slides", []):
            if slide.get("status") == "running":
                slide["status"] = "pending"
                slide.pop("started_at", None)
                slide["updated_at"] = utcnow()
                changed = True
        if changed:
            _refresh_job_counts(job)
            store.save_presentation_jobs(jobs)
        return job
    raise KeyError("Presentation job not found")


def pause_for_resource(job_id: str, reason: str = "GPU resource handoff") -> dict[str, Any]:
    job = reset_interrupted_slides(job_id)
    if job.get("status") not in ("queued", "running", "pausing"):
        return job
    try:
        build_pptx_output(job_id)
    except Exception as exc:
        print(f"Failed to build partial presentation during pause: {exc}", flush=True)
    return store.update_presentation_job(
        job_id,
        status="paused",
        paused_by_resource=True,
        pause_reason=reason,
        progress_label=f"Paused: {reason}",
        current_slide=None,
        stop_requested=False,
        updated_at=utcnow(),
    ) or job


def pause_active_presentations(reason: str = "GPU resource handoff") -> list[dict[str, Any]]:
    paused: list[dict[str, Any]] = []
    for job in store.load_presentation_jobs():
        if job.get("status") in ("queued", "running", "pausing"):
            paused.append(pause_for_resource(str(job["id"]), reason))
    return paused


def prepare_resume(job_id: str) -> dict[str, Any]:
    job = store.get_presentation_job_by_id(job_id)
    if not job:
        raise KeyError("Presentation job not found")
    if job.get("status") != "paused":
        return job
    reset_interrupted_slides(job_id)
    return store.update_presentation_job(
        job_id,
        status="queued",
        paused_by_resource=False,
        pause_reason=None,
        stop_requested=False,
        progress_label="Queued for resume",
        updated_at=utcnow(),
    ) or job


def _refresh_job_counts(job: dict[str, Any]) -> None:
    slides = job.get("slides", [])
    processed_statuses = {"completed", "empty", "flagged"}
    completed = sum(1 for slide in slides if slide.get("status") in processed_statuses)
    failed = sum(1 for slide in slides if slide.get("status") == "failed")
    total = max(1, int(job.get("total_slides") or len(slides) or 1))
    job["completed_slides"] = completed
    job["failed_slides"] = failed
    job["progress_percent"] = round((completed / total) * 100, 1)
    job["updated_at"] = utcnow()


def _synthesize_slide_audio(job_id: str, slide: dict[str, Any], model_id: str) -> dict[str, Any]:
    slide_index = int(slide["index"])
    text = str(slide.get("text") or "").strip()
    chunks = split_text(text, TARGET_CHUNK_CHARS) or [text]
    chunk_segments: list[AudioSegment] = []
    qualities: list[dict[str, Any]] = []
    for chunk_index, chunk_text in enumerate(chunks):
        wav_bytes, sr = synthesize_module.synthesize(text=chunk_text, model_id=model_id)
        quality = analyze_wav_quality(wav_bytes, sr, chunk_text)
        qualities.append(quality)
        mp3_bytes = wav_to_mp3_bytes(wav_bytes)
        chunk_path = _chunk_audio_path(job_id, slide_index, chunk_index)
        with open(chunk_path, "wb") as f:
            f.write(mp3_bytes)
        chunk_segments.append(AudioSegment.from_file(chunk_path, format="mp3"))
    silence = AudioSegment.silent(duration=500)
    combined = AudioSegment.empty()
    for idx, segment in enumerate(chunk_segments):
        if idx > 0:
            combined += silence
        combined += segment
    output_path = _slide_audio_path(job_id, slide_index)
    combined.export(output_path, format="mp3")
    reasons = [reason for quality in qualities for reason in quality.get("reasons", [])]
    duration = round(float(combined.duration_seconds), 3)
    return {
        "ok": not reasons,
        "reasons": reasons,
        "duration_seconds": duration,
        "chunks": len(chunks),
        "output_path": output_path,
        "output_bytes": os.path.getsize(output_path),
    }


def run_presentation_job(job_id: str) -> None:
    started = monotonic()
    job = store.get_presentation_job_by_id(job_id)
    if not job or job.get("status") == "stopped" or job.get("stop_requested"):
        return
    with tts_vram_guard("presentation", device=DEVICE):
        try:
            _run_presentation_job_inner(job_id, started)
        finally:
            synthesize_module.unload_cached_models()


def _run_presentation_job_inner(job_id: str, started: float) -> None:
    try:
        store.update_presentation_job(job_id, status="running", progress_label="Starting", started_at=utcnow(), stop_requested=False, updated_at=utcnow())
        while True:
            job = store.get_presentation_job_by_id(job_id)
            if not job:
                return
            if job.get("stop_requested"):
                out = build_pptx_output(job_id)
                store.update_presentation_job(job_id, status="stopped", progress_label="Stopped", output_path=out, current_slide=None, updated_at=utcnow())
                return
            slides = job.get("slides", [])
            next_slide = next((slide for slide in slides if slide.get("status") in ("pending", "failed", "flagged")), None)
            if not next_slide:
                out = build_pptx_output(job_id)
                elapsed = monotonic() - started
                store.update_presentation_job(
                    job_id,
                    status="completed",
                    progress_label="Complete",
                    progress_percent=100.0,
                    current_slide=None,
                    output_path=out,
                    elapsed_seconds=round(elapsed, 1),
                    finished_at=utcnow(),
                    updated_at=utcnow(),
                )
                return
            idx = int(next_slide["index"])
            store.update_presentation_slide(job_id, idx, status="running", started_at=utcnow(), updated_at=utcnow())
            job = store.get_presentation_job_by_id(job_id) or job
            store.update_presentation_job(
                job_id,
                status="running",
                current_slide=idx,
                progress_label=f"Generating slide {idx + 1} of {job.get('total_slides')}",
                elapsed_seconds=round(monotonic() - started, 1),
                updated_at=utcnow(),
            )
            try:
                quality = _synthesize_slide_audio(job_id, next_slide, str(job["model_id"]))
                status = "completed" if quality.get("ok") else "flagged"
                store.update_presentation_slide(
                    job_id,
                    idx,
                    status=status,
                    output_path=quality.get("output_path"),
                    output_bytes=quality.get("output_bytes"),
                    quality=quality,
                    audio_duration_seconds=quality.get("duration_seconds"),
                    finished_at=utcnow(),
                    updated_at=utcnow(),
                )
                build_pptx_output(job_id)
                if status == "flagged":
                    store.update_presentation_job(job_id, status="needs_review", progress_label=f"Slide {idx + 1} flagged: {', '.join(quality.get('reasons', []))}", current_slide=None, updated_at=utcnow())
                    return
            except Exception as exc:
                store.update_presentation_slide(job_id, idx, status="failed", error=str(exc), finished_at=utcnow(), updated_at=utcnow())
                store.update_presentation_job(job_id, status="failed", error=str(exc), progress_label="Failed", current_slide=None, updated_at=utcnow())
                return
    except Exception as exc:
        store.update_presentation_job(job_id, status="failed", error=str(exc), progress_label="Failed", current_slide=None, updated_at=utcnow())


def _ensure_default_content_type(root: ET.Element, extension: str, content_type: str) -> None:
    default_tag = f"{{{CONTENT_TYPES_NS}}}Default"
    for item in root.findall(default_tag):
        if item.attrib.get("Extension", "").lower() == extension.lower():
            item.attrib["ContentType"] = content_type
            return
    ET.SubElement(root, default_tag, {"Extension": extension, "ContentType": content_type})


def _max_shape_id(slide_root: ET.Element) -> int:
    max_id = 1
    for node in slide_root.findall(".//p:cNvPr", NS):
        try:
            max_id = max(max_id, int(node.attrib.get("id", "0")))
        except ValueError:
            continue
    return max_id


def _ensure_transition(slide_root: ET.Element, duration_ms: int) -> None:
    transition = slide_root.find("p:transition", NS)
    if transition is None:
        transition = ET.Element(qn("p", "transition"))
        timing = slide_root.find("p:timing", NS)
        if timing is not None:
            idx = list(slide_root).index(timing)
            slide_root.insert(idx, transition)
        else:
            slide_root.append(transition)
    transition.attrib["advClick"] = "0"
    transition.attrib["advTm"] = str(max(1, int(duration_ms)))


def _add_audio_shape(
    slide_root: ET.Element,
    media_rel_id: str,
    audio_rel_id: str,
    image_rel_id: str,
    shape_id: int,
) -> None:
    sp_tree = slide_root.find("p:cSld/p:spTree", NS)
    if sp_tree is None:
        raise ValueError("Slide does not have a shape tree")
    pic = ET.Element(qn("p", "pic"))
    nv_pic_pr = ET.SubElement(pic, qn("p", "nvPicPr"))
    c_nv_pr = ET.SubElement(nv_pic_pr, qn("p", "cNvPr"), {"id": str(shape_id), "name": f"Narration Audio {shape_id}"})
    ET.SubElement(c_nv_pr, qn("a", "hlinkClick"), {qn("r", "id"): "", "action": "ppaction://media"})
    c_nv_pic_pr = ET.SubElement(nv_pic_pr, qn("p", "cNvPicPr"))
    ET.SubElement(c_nv_pic_pr, qn("a", "picLocks"), {"noChangeAspect": "1"})
    nv_pr = ET.SubElement(nv_pic_pr, qn("p", "nvPr"))
    ET.SubElement(nv_pr, qn("a", "audioFile"), {qn("r", "link"): audio_rel_id})
    ext_lst = ET.SubElement(nv_pr, qn("p", "extLst"))
    ext = ET.SubElement(ext_lst, qn("p", "ext"), {"uri": "{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}"})
    ET.SubElement(ext, qn("p14", "media"), {qn("r", "embed"): media_rel_id})
    blip_fill = ET.SubElement(pic, qn("p", "blipFill"))
    ET.SubElement(blip_fill, qn("a", "blip"), {qn("r", "embed"): image_rel_id})
    stretch = ET.SubElement(blip_fill, qn("a", "stretch"))
    ET.SubElement(stretch, qn("a", "fillRect"))
    sp_pr = ET.SubElement(pic, qn("p", "spPr"))
    xfrm = ET.SubElement(sp_pr, qn("a", "xfrm"))
    ET.SubElement(xfrm, qn("a", "off"), {"x": "127000", "y": "127000"})
    ET.SubElement(xfrm, qn("a", "ext"), {"cx": "304800", "cy": "304800"})
    geometry = ET.SubElement(sp_pr, qn("a", "prstGeom"), {"prst": "rect"})
    ET.SubElement(geometry, qn("a", "avLst"))
    sp_tree.append(pic)


def _ensure_audio_timing(slide_root: ET.Element, shape_id: int, audio_duration_ms: int) -> None:
    existing = slide_root.find("p:timing", NS)
    if existing is not None:
        slide_root.remove(existing)
    timing = ET.fromstring(
        f'''<p:timing xmlns:p="{NS["p"]}"><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst><p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst><p:par><p:cTn id="3" fill="hold"><p:stCondLst><p:cond delay="indefinite"/><p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond></p:stCondLst><p:childTnLst><p:par><p:cTn id="4" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst><p:par><p:cTn id="5" presetID="1" presetClass="mediacall" presetSubtype="0" fill="hold" nodeType="withEffect"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst><p:cmd type="call" cmd="playFrom(0.0)"><p:cBhvr><p:cTn id="6" dur="{audio_duration_ms}" fill="hold"/><p:tgtEl><p:spTgt spid="{shape_id}"/></p:tgtEl></p:cBhvr></p:cmd></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst><p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>'''
    )
    root_ext_lst = slide_root.find("p:extLst", NS)
    if root_ext_lst is not None:
        slide_root.insert(list(slide_root).index(root_ext_lst), timing)
    else:
        slide_root.append(timing)


def _add_audio_relationships(
    files: dict[str, bytes],
    slide_path: str,
    media_name: str,
) -> tuple[str, str, str]:
    rels_path = rels_path_for(slide_path)
    rels = parse_xml(files[rels_path]) if rels_path in files else ET.Element(qn("rel", "Relationships"))
    media_rel_id = _next_rel_id(rels)
    ET.SubElement(rels, qn("rel", "Relationship"), {"Id": media_rel_id, "Type": MEDIA_REL_TYPE, "Target": f"../media/{media_name}"})
    audio_rel_id = _next_rel_id(rels)
    ET.SubElement(rels, qn("rel", "Relationship"), {"Id": audio_rel_id, "Type": AUDIO_REL_TYPE, "Target": f"../media/{media_name}"})
    image_rel_id = _next_rel_id(rels)
    ET.SubElement(rels, qn("rel", "Relationship"), {"Id": image_rel_id, "Type": IMAGE_REL_TYPE, "Target": f"../media/{Path(AUDIO_PLACEHOLDER_NAME).name}"})
    files[rels_path] = xml_bytes(rels)
    return media_rel_id, audio_rel_id, image_rel_id


def _powerpoint_safe_mp3(path: str) -> tuple[bytes, int]:
    """Normalize narration so PowerPoint reports and plays its full duration."""
    audio = AudioSegment.from_file(path, format="mp3").set_frame_rate(44100).set_channels(1)
    output = BytesIO()
    audio.export(output, format="mp3", bitrate="128k")
    return output.getvalue(), len(audio)


def build_pptx_output(job_id: str) -> str:
    job = store.get_presentation_job_by_id(job_id)
    if not job:
        raise KeyError("Presentation job not found")
    source = job.get("source_path") or _source_path(job_id)
    output = job.get("output_path") or _output_path(job_id)
    with zipfile.ZipFile(source, "r") as zf:
        files = {name: zf.read(name) for name in zf.namelist()}
        content_types = parse_xml(files["[Content_Types].xml"])
        _ensure_default_content_type(content_types, "mp3", MP3_CONTENT_TYPE)
        _ensure_default_content_type(content_types, "png", "image/png")
        files["[Content_Types].xml"] = xml_bytes(content_types)
        files[AUDIO_PLACEHOLDER_NAME] = AUDIO_PLACEHOLDER_PNG
        for slide in job.get("slides", []):
            slide_path = slide.get("slide_path")
            if not slide_path or slide_path not in files:
                continue
            slide_root = parse_xml(files[slide_path])
            duration_ms = EMPTY_SLIDE_ADVANCE_MS
            path = slide.get("output_path")
            has_audio = slide.get("status") in ("completed", "flagged") and path and os.path.exists(path)
            if has_audio:
                media_name = f"narration_{job_id}_slide_{int(slide['index']) + 1:05d}.mp3"
                media_bytes, audio_duration_ms = _powerpoint_safe_mp3(path)
                files[f"ppt/media/{media_name}"] = media_bytes
                media_rel_id, audio_rel_id, image_rel_id = _add_audio_relationships(files, slide_path, media_name)
                shape_id = _max_shape_id(slide_root) + 1
                _add_audio_shape(slide_root, media_rel_id, audio_rel_id, image_rel_id, shape_id)
                _ensure_audio_timing(slide_root, shape_id, audio_duration_ms + NARRATION_MEDIA_GUARD_MS)
                duration_ms = max(EMPTY_SLIDE_ADVANCE_MS, audio_duration_ms + NARRATION_ADVANCE_PAD_MS)
            _ensure_transition(slide_root, duration_ms)
            files[slide_path] = xml_bytes(slide_root)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    temp_output = f"{output}.tmp"
    with zipfile.ZipFile(temp_output, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for name, data in files.items():
            out.writestr(name, data)
    try:
        validate_pptx(temp_output)
        os.replace(temp_output, output)
    finally:
        if os.path.exists(temp_output):
            os.remove(temp_output)
    store.update_presentation_job(job_id, output_path=output, output_bytes=os.path.getsize(output), output_built_at=utcnow(), updated_at=utcnow())
    return output
