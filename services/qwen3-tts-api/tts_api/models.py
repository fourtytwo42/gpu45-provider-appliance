"""
Train CustomVoice models from voices and generate sample audio.
Training runs in a background thread; this module provides the sync workflow.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Iterator, Optional

import torch
import soundfile as sf
from huggingface_hub import snapshot_download

from qwen_tts import Qwen3TTSModel

from tts_api.config import API_DATA_DIR, BASE_MODEL, DEVICE, TOKENIZER_MODEL
from tts_api.store import MODELS_DIR
from tts_api.constants import MODEL_SAMPLE_SENTENCE, VOICE_PARAGRAPH_TEXT
from tts_api import store
from tts_api.resource_guard import tts_vram_guard

# Num epochs in sft_12hz (we use last checkpoint).
NUM_EPOCHS = 3
LAST_EPOCH = NUM_EPOCHS - 1


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _finetuning_dir() -> str:
    return os.path.join(_repo_root(), "finetuning")


def _utcnow() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _patch_sft_attention() -> None:
    script_path = os.path.join(_finetuning_dir(), "sft_12hz.py")
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        patched = content.replace('attn_implementation="flash_attention_2"', 'attn_implementation="sdpa"')
        if patched != content:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(patched)
    except OSError:
        pass


def _resolve_model_path(model_path: str) -> str:
    if os.path.isdir(model_path):
        return os.path.abspath(model_path)
    if "/" not in model_path:
        return model_path
    return snapshot_download(repo_id=model_path)


def _truthy(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _systemctl(action: str, service: str) -> None:
    result = subprocess.run(["/usr/bin/sudo", "-n", "/usr/bin/systemctl", action, service], capture_output=True, text=True)
    if result.returncode != 0:
        result = subprocess.run(["/usr/bin/systemctl", action, service], capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Unable to {action} {service}: {message}")


def _service_is_active(service: str) -> bool:
    result = subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", service], check=False)
    return result.returncode == 0


@contextmanager
def _exclusive_training_guard() -> Iterator[None]:
    if not _truthy(os.environ.get("QWEN_TTS_TRAINING_EXCLUSIVE_LLM"), True):
        yield
        return

    service = os.environ.get("QWEN_TTS_LLM_SERVICE", "llama-openai.service")
    restart_after = _truthy(os.environ.get("QWEN_TTS_RESTART_LLM_AFTER"), True)
    was_active = _service_is_active(service)
    if was_active:
        print(f"[training-guard] stopping {service} for exclusive TTS model training", flush=True)
        _systemctl("stop", service)
        time.sleep(3)
    try:
        yield
    finally:
        if was_active and restart_after:
            print(f"[training-guard] restarting {service} after TTS model training", flush=True)
            _systemctl("start", service)


def run_training_sync(
    voice_id: str,
    model_id: str,
    model_name: str,
    progress: Optional[Callable[[str, float, Optional[float]], None]] = None,
) -> Dict[str, Any]:
    """
    Full training pipeline: build JSONL, prepare_data, sft_12hz, generate sample WAV.
    Call this from a background thread. Returns the model record to append to store.
    """
    voice = store.get_voice_by_id(voice_id)
    if not voice:
        raise KeyError(f"Voice not found: {voice_id}")

    paragraph_path = voice.get("paragraph_path")
    if not paragraph_path or not os.path.exists(paragraph_path):
        raise FileNotFoundError(f"Voice paragraph audio not found: {paragraph_path}")

    paragraph_path_abs = os.path.abspath(paragraph_path)
    paragraph_text = (voice.get("paragraph_text") or VOICE_PARAGRAPH_TEXT).strip()
    raw_jsonl = store.model_train_raw_path(model_id)
    codes_jsonl = store.model_train_codes_path(model_id)
    os.makedirs(store.model_dir(model_id), exist_ok=True)

    started = time.monotonic()

    def set_progress(label: str, percent: float, eta_seconds: Optional[float] = None) -> None:
        if progress:
            progress(label, max(0.0, min(100.0, percent)), eta_seconds)

    def elapsed() -> float:
        return max(0.0, time.monotonic() - started)

    with _exclusive_training_guard():
        base_model_path = _resolve_model_path(BASE_MODEL)

        # Single-sample training: same file for audio and ref_audio.
        set_progress("Preparing training manifest", 5.0, 360.0)
        with open(raw_jsonl, "w", encoding="utf-8") as f:
            line = json.dumps({
                "audio": paragraph_path_abs,
                "text": paragraph_text,
                "ref_audio": paragraph_path_abs,
            }, ensure_ascii=False) + "\n"
            f.write(line)

        # prepare_data.py: add audio_codes
        prep_cmd = [
            sys.executable,
            os.path.join(_finetuning_dir(), "prepare_data.py"),
            "--device", DEVICE,
            "--tokenizer_model_path", TOKENIZER_MODEL,
            "--input_jsonl", os.path.abspath(raw_jsonl),
            "--output_jsonl", os.path.abspath(codes_jsonl),
        ]
        set_progress("Encoding training audio", 15.0, 300.0)
        result = subprocess.run(prep_cmd, cwd=_repo_root(), capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"prepare_data failed: {result.stderr or result.stdout}")

        # sft_12hz.py: train and write checkpoints
        checkpoint_base = os.path.join(store.model_dir(model_id), store.CHECKPOINT_DIR)
        speaker_name = store.slug_from_name(model_name)
        _patch_sft_attention()
        sft_cmd = [
            sys.executable,
            "sft_12hz.py",
            "--init_model_path", base_model_path,
            "--output_model_path", os.path.abspath(checkpoint_base),
            "--train_jsonl", os.path.abspath(codes_jsonl),
            "--batch_size", "1",
            "--num_epochs", str(NUM_EPOCHS),
            "--speaker_name", speaker_name,
        ]
        set_progress("Fine-tuning voice model", 30.0, 300.0)
        process = subprocess.Popen(
            sft_cmd,
            cwd=_finetuning_dir(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        output_lines = []
        stop_monitor = threading.Event()

        def monitor_training() -> None:
            while not stop_monitor.wait(5):
                current = elapsed()
                estimate = 360.0
                fraction = min(0.95, current / estimate)
                set_progress("Fine-tuning voice model", 30.0 + (fraction * 55.0), max(0.0, estimate - current))

        monitor = threading.Thread(target=monitor_training, daemon=True)
        monitor.start()
        assert process.stdout is not None
        for line in process.stdout:
            output_lines.append(line)
            if "Epoch " in line and "Step " in line:
                try:
                    epoch_text = line.split("Epoch ", 1)[1].split("|", 1)[0].strip()
                    epoch = int(epoch_text)
                    set_progress(
                        f"Fine-tuning epoch {epoch + 1}/{NUM_EPOCHS}",
                        30.0 + ((epoch + 1) / NUM_EPOCHS * 55.0),
                        None,
                    )
                except (IndexError, ValueError):
                    pass
        return_code = process.wait()
        stop_monitor.set()
        if return_code != 0:
            raise RuntimeError(f"sft_12hz failed: {''.join(output_lines)}")

        checkpoint_path = store.model_checkpoint_path(model_id, LAST_EPOCH)
        if not os.path.isdir(checkpoint_path):
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        # Generate sample sentence WAV with the new CustomVoice model
        set_progress("Generating model sample", 90.0, 120.0)
        sample_path = store.model_sample_path(model_id)
        _generate_model_sample(checkpoint_path, speaker_name, sample_path)
        set_progress("Complete", 100.0, 0.0)

    return {
        "id": model_id,
        "name": model_name,
        "voice_id": voice_id,
        "model_path": checkpoint_path,
        "speaker_name": speaker_name,
        "sample_path": sample_path,
        "created_at": _utcnow(),
    }


def _generate_model_sample(checkpoint_path: str, speaker_name: str, out_path: str) -> None:
    """Load CustomVoice checkpoint and generate MODEL_SAMPLE_SENTENCE to out_path."""
    with tts_vram_guard("generate_model_sample", device=DEVICE):
        model = Qwen3TTSModel.from_pretrained(
            checkpoint_path,
            device_map=DEVICE,
            dtype=torch.bfloat16,
        )
        try:
            wavs, sr = model.generate_custom_voice(
                text=MODEL_SAMPLE_SENTENCE,
                speaker=speaker_name,
                language="English",
            )
            sf.write(out_path, wavs[0], sr)
        finally:
            del model
            if torch.cuda.is_available():
                torch.cuda.empty_cache()


def rename_model(model_id: str, name: str) -> Dict[str, Any]:
    """Rename a model. Enforces unique name."""
    models = store.load_models()
    name = (name or "").strip()
    if not name:
        raise ValueError("Name cannot be empty")
    existing = store.get_model_by_name(name)
    if existing and existing.get("id") != model_id:
        raise ValueError(f"Model name already exists: {name}")
    for m in models:
        if m.get("id") == model_id:
            m["name"] = name
            store.save_models(models)
            return m
    raise KeyError(f"Model not found: {model_id}")


def delete_model(model_id: str) -> None:
    """Remove model metadata and entire model directory (checkpoint, sample, JSONL)."""
    models = store.load_models()
    kept = []
    for m in models:
        if m.get("id") == model_id:
            model_dir_path = os.path.join(API_DATA_DIR, MODELS_DIR, model_id)
            if os.path.isdir(model_dir_path):
                try:
                    shutil.rmtree(model_dir_path)
                except OSError:
                    pass
            continue
        kept.append(m)
    if len(kept) == len(models):
        raise KeyError(f"Model not found: {model_id}")
    store.save_models(kept)
