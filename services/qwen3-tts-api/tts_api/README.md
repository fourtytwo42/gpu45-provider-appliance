# Qwen3-TTS Generator API

REST API for creating voices from prompts, training CustomVoice models from those voices, and synthesizing speech. API only (no UI). Runs as a long-lived service; bind to `0.0.0.0` to allow access from other machines on your LAN. All audio returned by the API is MP3 (`audio/mpeg`).

## Run the server

From the project root (Qwen3-TTS):

```bash
# Install dependencies (includes fastapi, uvicorn)
pip install -e .

# Run API (default: host 0.0.0.0, port 8000)
python -m tts_api
# or
qwen-tts-api
# or
uvicorn tts_api.main:app --host 0.0.0.0 --port 8000
```

**LAN access:** Binding to `0.0.0.0` makes the API reachable from other devices on your network. Use `http://<this-machine-ip>:8000` from another machine (e.g. `http://192.168.1.100:8000`). Port 8000 must be allowed through the host firewall if needed.

**MP3 encoding:** Audio responses are converted from WAV to MP3 the same way as the audiobook scripts: **ffmpeg** (system PATH or from `pip install imageio-ffmpeg`). Same as `witness_audiobook_organize.py` and `generate_audiobook_credits.py`.

## Configuration (environment)

| Variable | Default | Description |
|---------|---------|-------------|
| `QWEN_TTS_API_HOST` | `0.0.0.0` | Bind address |
| `QWEN_TTS_API_PORT` | `8000` | Port |
| `QWEN_TTS_API_DATA` | `./api_data` | Directory for voices, models, and JSON stores (relative to cwd) |
| `QWEN_TTS_DEVICE` | `cuda:0` | Device for inference and training |

## API overview

- **Voices:** Create from a text prompt (VoiceDesign), get paragraph sample, rename, delete.
- **Models:** Train a CustomVoice model from a voice (async; returns 202, poll for status). Get sample sentence, rename, delete.
- **Synthesize:** Generate WAV using a voice, a trained model, or the default (VoiceDesign, no instruct).

Default synthesis (when you do not pass `voice_id` or `model_id`) uses VoiceDesign with an empty instruction.

Interactive docs: `http://0.0.0.0:8000/docs` (Swagger UI).

## Endpoints

- `GET /health` – Health check.
- `POST /voices` – Create voice (body: `instruct`, `language`, optional `name`).
- `GET /voices`, `GET /voices/{id}`, `GET /voices/{id}/sample` – List, get, get paragraph WAV.
- `PATCH /voices/{id}`, `DELETE /voices/{id}` – Rename, delete.
- `POST /models` – Start training (body: `voice_id`, optional `name`). Returns 202; poll `GET /models/{id}` for `status`: `ready` or `failed`.
- `GET /models`, `GET /models/{id}`, `GET /models/{id}/sample` – List, get, get sample sentence WAV.
- `PATCH /models/{id}`, `DELETE /models/{id}` – Rename, delete.
- `POST /synthesize` – Body: `text` and one of `voice_id`, `model_id`, or `use_default: true`. Returns `audio/mpeg` (MP3).
