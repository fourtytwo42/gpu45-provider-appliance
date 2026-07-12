from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from io import BytesIO
from typing import Any

import soundfile as sf

from tts_api import store
from tts_api import synthesize as qwen_synthesize


POCKET_URL = os.environ.get("POCKET_TTS_URL", "http://127.0.0.1:8002").rstrip("/")
SUPPORTED_ENGINES = {"qwen", "pocket"}


def normalize_engine(engine: str | None) -> str:
    value = (engine or "qwen").strip().lower()
    if value not in SUPPORTED_ENGINES:
        raise ValueError(f"Unsupported TTS engine: {value}")
    return value


def _pocket_json(path: str, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{POCKET_URL}{path}", data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=3600) as response:
            body = response.read()
            if response.headers.get_content_type() == "application/json":
                return json.loads(body)
            return body
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Pocket TTS returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Pocket TTS is unavailable: {exc.reason}") from exc


def resolve_voice(engine: str | None, voice_id: str) -> dict[str, Any]:
    selected = normalize_engine(engine)
    if selected == "qwen":
        model = store.get_model_by_id(voice_id)
        if not model:
            raise KeyError(f"Model not found: {voice_id}")
        if model.get("status") != "ready":
            raise ValueError("Model is not ready")
        return {"id": voice_id, "name": model.get("name") or voice_id, "engine": selected}
    voices = _pocket_json("/voices")
    voice = next((item for item in voices if item.get("id") == voice_id), None)
    if not voice:
        raise KeyError(f"Pocket voice not found: {voice_id}")
    return {**voice, "engine": selected}


def synthesize(text: str, engine: str | None, voice_id: str) -> tuple[bytes, int]:
    selected = normalize_engine(engine)
    if selected == "qwen":
        return qwen_synthesize.synthesize(text=text, model_id=voice_id)
    wav_bytes = _pocket_json("/synthesize", {"text": text, "voice_id": voice_id})
    sample_rate = int(sf.info(BytesIO(wav_bytes)).samplerate)
    return wav_bytes, sample_rate


def unload(engine: str | None) -> None:
    if normalize_engine(engine) == "qwen":
        qwen_synthesize.unload_cached_models()
