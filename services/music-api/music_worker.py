#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path


def atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def progress(path: Path, value: float, stage: str, eta: int | None = None) -> None:
    atomic_json(path, {"progress": round(max(0, min(99, value)), 1), "stage": stage, "etaSeconds": eta})


def probe_audio(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries", "format=duration:stream=sample_rate,channels,codec_name",
            "-of", "json", str(path),
        ],
        capture_output=True,text=True,timeout=60,check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Generated audio failed validation: {result.stderr.strip()}")
    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or [{}]
    stream = streams[0] if streams else {}
    duration = float((payload.get("format") or {}).get("duration") or 0)
    if duration <= 0.5:
        raise RuntimeError("Generated audio is empty or too short.")
    return {
        "durationSeconds": round(duration, 3),
        "sampleRate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
        "codec": stream.get("codec_name"),
    }


def run_ace(spec: dict[str, object], progress_path: Path) -> tuple[dict[str, str], dict[str, object]]:
    source_root = Path(os.environ.get("GPU45_ACE_ROOT", "/opt/ace-step-1.5"))
    checkpoints = Path(os.environ.get("ACESTEP_CHECKPOINTS_DIR", "/models/music/ace-step/checkpoints"))
    sys.path.insert(0, str(source_root))
    os.environ.setdefault("ACESTEP_PROJECT_ROOT", str(source_root))
    os.environ.setdefault("ACESTEP_CHECKPOINTS_DIR", str(checkpoints))
    os.environ.setdefault("ACESTEP_ROCM_DTYPE", "bfloat16")
    os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    import torch
    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    job = spec["job"]
    payload = job["payload"]
    profile = spec["profile"]
    output_dir = Path(str(spec["outputDir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    progress(progress_path, 3, "loading-ace-model")
    dit_handler = AceStepHandler()
    status, success = dit_handler.initialize_service(
        project_root=str(source_root),config_path=str(profile["model"]),device="cuda",
        use_flash_attention=False,compile_model=False,offload_to_cpu=False,
        offload_dit_to_cpu=False,quantization=None,prefer_source="huggingface",use_mlx_dit=False,
    )
    if not success:
        raise RuntimeError(str(status))

    task_type = str(job["task_type"])
    thinking = bool(payload.get("thinking", True)) and task_type in {"text2music", "complete", "lego"}
    llm_handler = None
    if thinking:
        progress(progress_path, 14, "loading-ace-language-model")
        llm_handler = LLMHandler()
        status, success = llm_handler.initialize(
            checkpoint_dir=str(checkpoints),lm_model_path=str(profile["lmModel"]),
            backend=os.environ.get("GPU45_ACE_LM_BACKEND", "pt"),device="cuda",
            offload_to_cpu=False,dtype=torch.bfloat16,
        )
        if not success:
            raise RuntimeError(str(status))

    def generation_progress(value: float, desc: str | None = None, **_kwargs: object) -> None:
        numeric = float(value)
        mapped = 20 + max(0, min(1, numeric)) * 74
        elapsed = max(0.1, time.monotonic() - started)
        eta = int((elapsed / mapped) * (96 - mapped)) if mapped > 1 else None
        progress(progress_path, mapped, str(desc or "generating-audio").strip().lower().replace(" ", "-"), eta)

    seed = int(payload.get("seed") or -1)
    output_format = str(payload.get("output_format") or payload.get("outputFormat") or "flac")
    params = GenerationParams(
        task_type=task_type,
        instruction=str(payload.get("instruction") or "Fill the audio semantic mask based on the given conditions:"),
        reference_audio=str(payload.get("reference_audio") or "") or None,
        src_audio=str(payload.get("source_audio") or payload.get("src_audio") or "") or None,
        caption=str(payload.get("caption") or ""),
        lyrics=str(payload.get("lyrics") or ("[Instrumental]" if payload.get("instrumental") else "")),
        instrumental=bool(payload.get("instrumental", False)),
        vocal_language=str(payload.get("language") or payload.get("vocal_language") or "unknown"),
        bpm=int(payload["bpm"]) if payload.get("bpm") not in (None, "", "auto") else None,
        keyscale=str(payload.get("key") or payload.get("keyscale") or ""),
        timesignature=str(payload.get("time_signature") or payload.get("timesignature") or ""),
        duration=float(payload.get("duration") or 60),
        inference_steps=int(payload.get("steps") or profile.get("defaultSteps") or 8),
        seed=seed,
        guidance_scale=float(payload.get("guidance_scale") or 7.0),
        repainting_start=float(payload.get("repainting_start") or 0),
        repainting_end=float(payload.get("repainting_end") or -1),
        audio_cover_strength=float(payload.get("reference_strength") or payload.get("audio_cover_strength") or 1.0),
        thinking=thinking,
        lm_temperature=float(payload.get("lm_temperature") or 0.85),
        lm_top_p=float(payload.get("lm_top_p") or 0.9),
        lm_top_k=int(payload.get("lm_top_k") or 0),
        use_cot_metas=thinking,
        use_cot_caption=thinking,
        use_cot_language=thinking,
    )
    config = GenerationConfig(
        batch_size=1,use_random_seed=seed < 0,seeds=None if seed < 0 else [seed],
        allow_lm_batch=False,lm_batch_chunk_size=1,audio_format=output_format,
    )
    progress(progress_path, 20, "generating-audio")
    result = generate_music(dit_handler, llm_handler, params, config, save_dir=str(output_dir), progress=generation_progress)
    if not result.success or not result.audios:
        raise RuntimeError(str(result.error or result.status_message or "ACE-Step did not return audio."))
    source = Path(str(result.audios[0]["path"]))
    master = output_dir / f"master.{output_format}"
    if source.resolve() != master.resolve():
        shutil.copy2(source, master)
    progress(progress_path, 97, "validating-audio")
    metrics = probe_audio(master)
    metrics["backend"] = "ace-step-1.5"
    metrics["realTimeFactor"] = round((time.monotonic() - started) / float(metrics["durationSeconds"]), 4)
    return {"master": str(master)}, metrics


def run_phase(command: list[str], cwd: Path, progress_path: Path, value: float, stage: str) -> None:
    progress(progress_path, value, stage)
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"LeVo phase failed ({stage}) with status {result.returncode}.")


def run_levo(spec: dict[str, object], progress_path: Path) -> tuple[dict[str, str], dict[str, object]]:
    root = Path(os.environ.get("GPU45_LEVO_ROOT", "/opt/levo2-amd"))
    job = spec["job"]
    payload = job["payload"]
    output_dir = Path(str(spec["outputDir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    batch = f"gpu45-{job['id']}"
    input_dir = root / "gpu45-inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    input_path = input_dir / f"{batch}.jsonl"
    lyric = str(payload.get("lyrics") or "[intro-short] ; [inst-medium] ; [outro-short]")
    item: dict[str, object] = {"idx": "master", "gt_lyric": lyric, "descriptions": str(payload.get("caption") or "")}
    reference = payload.get("reference_audio")
    if reference:
        item["prompt_audio_path"] = str(reference)
    input_path.write_text(json.dumps(item) + "\n", encoding="utf-8")
    python = sys.executable
    started = time.monotonic()

    run_phase([python, "jsonl2conditions.py", "--jsonl", str(input_path)], root, progress_path, 5, "levo-conditioning")
    run_phase([python, "conditions2cb0tokens.py", "--batch", batch], root, progress_path, 20, "levo-main-tokens")
    run_phase([python, "cb0tokens2tokens.py", "--batch", batch], root, progress_path, 58, "levo-sub-tokens")
    run_phase([python, "tokens2audio.py", "--batch", batch], root, progress_path, 82, "levo-audio-synthesis")

    source = root / "out" / batch / "master.wav"
    if not source.is_file():
        raise RuntimeError("LeVo completed without producing master.wav.")
    master = output_dir / "master.wav"
    shutil.copy2(source, master)
    progress(progress_path, 97, "validating-audio")
    metrics = probe_audio(master)
    metrics["backend"] = "levo2-amd"
    metrics["realTimeFactor"] = round((time.monotonic() - started) / float(metrics["durationSeconds"]), 4)
    return {"master": str(master)}, metrics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    progress_path = Path(str(spec["progressPath"]))
    result_path = Path(str(spec["resultPath"]))
    try:
        if spec["profile"]["backend"] == "ace":
            assets, metrics = run_ace(spec, progress_path)
        else:
            assets, metrics = run_levo(spec, progress_path)
        atomic_json(result_path, {"ok": True, "assets": assets, "metrics": metrics})
        return 0
    except Exception as exc:
        traceback.print_exc()
        atomic_json(result_path, {"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

