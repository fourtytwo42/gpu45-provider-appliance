"""
Synthesis: VoiceDesign (voice_id or default) or CustomVoice (model_id).
Returns WAV bytes or (samples, sample_rate) for streaming to response.
"""
from typing import Optional, Tuple

import torch
import soundfile as sf
import io

from qwen_tts import Qwen3TTSModel

from tts_api.config import API_DATA_DIR, DEVICE, VOICE_DESIGN_MODEL
from tts_api import store
from tts_api.resource_guard import tts_vram_guard


# Simple in-memory cache: one VoiceDesign model, one CustomVoice model by path.
_voice_design_model: Optional[Qwen3TTSModel] = None
_custom_voice_models: dict = {}  # model_path -> Qwen3TTSModel


def _get_voice_design_model() -> Qwen3TTSModel:
    global _voice_design_model
    if _voice_design_model is None:
        _voice_design_model = Qwen3TTSModel.from_pretrained(
            VOICE_DESIGN_MODEL,
            device_map=DEVICE,
            dtype=torch.bfloat16,
        )
    return _voice_design_model


def _get_custom_voice_model(model_path: str) -> Qwen3TTSModel:
    global _custom_voice_models
    if model_path not in _custom_voice_models:
        _custom_voice_models[model_path] = Qwen3TTSModel.from_pretrained(
            model_path,
            device_map=DEVICE,
            dtype=torch.bfloat16,
        )
    return _custom_voice_models[model_path]


def synthesize(
    text: str,
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None,
    use_default: bool = False,
) -> Tuple[bytes, int]:
    """
    Generate speech WAV. Returns (wav_bytes, sample_rate).
    Exactly one of voice_id, model_id, or use_default must be used.
    """
    if sum((voice_id is not None, model_id is not None, use_default)) != 1:
        raise ValueError("Specify exactly one of voice_id, model_id, or use_default")

    with tts_vram_guard("synthesize", device=DEVICE):
        if voice_id is not None:
            voice = store.get_voice_by_id(voice_id)
            if not voice:
                raise KeyError(f"Voice not found: {voice_id}")
            model = _get_voice_design_model()
            wavs, sr = model.generate_voice_design(
                text=text,
                instruct=voice.get("instruct") or "",
                language=voice.get("language") or "English",
            )
            wav = wavs[0]
        elif model_id is not None:
            model_record = store.get_model_by_id(model_id)
            if not model_record:
                raise KeyError(f"Model not found: {model_id}")
            model_path = model_record.get("model_path")
            speaker_name = model_record.get("speaker_name")
            if not model_path or not speaker_name:
                raise ValueError("Model record missing model_path or speaker_name")
            model = _get_custom_voice_model(model_path)
            wavs, sr = model.generate_custom_voice(
                text=text,
                speaker=speaker_name,
                language="English",
            )
            wav = wavs[0]
        else:
            # Default: VoiceDesign with empty instruct
            model = _get_voice_design_model()
            wavs, sr = model.generate_voice_design(
                text=text,
                instruct="",
                language="English",
            )
            wav = wavs[0]

    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV")
    return buf.getvalue(), sr


def synthesize_to_file_path(
    text: str,
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None,
    use_default: bool = False,
    output_path: Optional[str] = None,
) -> str:
    """Generate speech and optionally write to a file. Returns path or writes to api_data/audio."""
    wav_bytes, sr = synthesize(text=text, voice_id=voice_id, model_id=model_id, use_default=use_default)
    if output_path is None:
        import os
        from datetime import datetime
        audio_dir = os.path.join(API_DATA_DIR, store.AUDIO_DIR)
        os.makedirs(audio_dir, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(audio_dir, f"synthesize_{ts}.wav")
    with open(output_path, "wb") as f:
        f.write(wav_bytes)
    return output_path
