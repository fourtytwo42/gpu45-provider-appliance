# Qwen3-TTS API Reference

Complete reference for integrating with the TTS Generator API. Use this to call each endpoint from your app, scripts, or other services.

**Server (this host):** `http://192.168.50.239:8000`

**Base URL:** Use the server URL above to call the API from this machine or from any device on your LAN. When calling from the same machine that is running the API, you can also use `http://127.0.0.1:8000`.

**Content type:** Send `Content-Type: application/json` for any request that has a JSON body.

---

## Table of contents

1. [Health](#health)
2. [Voices](#voices)
3. [Models](#models)
4. [Synthesize](#synthesize)
5. [Error responses](#error-responses)
6. [Integration tips](#integration-tips)

---

## Health

### GET /health

Check that the API is running. Use for monitoring or before starting a flow.

**Request:** No body.

**Response:** `200 OK`

```json
{
  "status": "ok"
}
```

**Example (curl):**

```bash
curl -X GET "http://192.168.50.239:8000/health"
```

**Example (JavaScript fetch):**

```javascript
const res = await fetch('http://192.168.50.239:8000/health');
const data = await res.json();
console.log(data.status); // "ok"
```

---

## Voices

Voices are created from a text prompt (VoiceDesign). Each voice gets a fixed paragraph of audio you can preview, then optionally use to train a CustomVoice model.

### POST /voices

Create a new voice from an instruction string. The server generates a fixed paragraph with that style and stores it. This can take 30–90 seconds while the model loads and generates.

**Request body:**

| Field      | Type   | Required | Description |
|-----------|--------|----------|-------------|
| `instruct` | string | Yes      | Voice instruction for VoiceDesign (e.g. "Calm male narrator, clear and neutral."). |
| `language` | string | No       | Language code. Default: `"English"`. |
| `name`     | string | No       | Display name for the voice. Must be unique. If omitted, a default like `voice_<id>` is used. |

**Example body:**

```json
{
  "instruct": "Calm male narrator, clear and neutral. Slight gravitas.",
  "language": "English",
  "name": "my_narrator"
}
```

**Response:** `201 Created`

```json
{
  "id": "906f12d0-4a2b-4c3d-8e1f-123456789abc",
  "name": "my_narrator",
  "instruct": "Calm male narrator, clear and neutral. Slight gravitas.",
  "language": "English",
  "paragraph_text": "The quick brown fox jumps over the lazy dog. ...",
  "paragraph_path": "/path/to/api_data/voices/906f12d0.../paragraph.wav",
  "created_at": "2026-02-04T12:00:00.000000Z"
}
```

**Example (curl):**

```bash
curl -X POST "http://192.168.50.239:8000/voices" \
  -H "Content-Type: application/json" \
  -d "{\"instruct\": \"Calm male narrator, clear and neutral.\", \"language\": \"English\", \"name\": \"my_narrator\"}"
```

**Example (Python):**

```python
import requests

r = requests.post(
    "http://192.168.50.239:8000/voices",
    json={
        "instruct": "Calm male narrator, clear and neutral.",
        "language": "English",
        "name": "my_narrator",
    },
)
r.raise_for_status()
voice = r.json()
voice_id = voice["id"]
```

**Errors:**

- `400 Bad Request` – Invalid body or `name` already in use. Response body: `{"detail": "Voice name already exists: my_narrator"}`.

---

### GET /voices

List all voices **created via the API** (from POST /voices). Does not include built-in model speakers; use GET /voices/builtin for those.

**Request:** No body.

**Response:** `200 OK` – JSON array of voice objects (same shape as a single voice from POST /voices).

**Example (curl):**

```bash
curl -X GET "http://192.168.50.239:8000/voices"
```

**Example (Python):**

```python
r = requests.get("http://192.168.50.239:8000/voices")
voices = r.json()
for v in voices:
    print(v["id"], v["name"], v["instruct"][:50])
```

---

### GET /voices/builtin

List **built-in speakers** from the CustomVoice model (Ryan, Aiden, Vivian, etc.). These are reference only; the current API does not synthesize using a built-in speaker by name (you use API-created voices, trained models, or the default VoiceDesign).

**Request:** No body.

**Response:** `200 OK`

```json
{
  "speakers": [
    {
      "name": "Ryan",
      "description": "Dynamic male voice with strong rhythmic drive",
      "native_language": "English"
    },
    {
      "name": "Aiden",
      "description": "Sunny American male voice with a clear midrange",
      "native_language": "English"
    }
  ]
}
```

**Example (curl):**

```bash
curl -X GET "http://192.168.50.239:8000/voices/builtin"
```

**Example (Python):**

```python
r = requests.get("http://192.168.50.239:8000/voices/builtin")
data = r.json()
for s in data["speakers"]:
    print(s["name"], s["native_language"])
```

---

### GET /voices/{voice_id}

Get one voice by ID.

**Path parameter:** `voice_id` – UUID of the voice.

**Response:** `200 OK` – Single voice object.

**Example (curl):**

```bash
curl -X GET "http://192.168.50.239:8000/voices/906f12d0-4a2b-4c3d-8e1f-123456789abc"
```

**Errors:**

- `404 Not Found` – No voice with that ID. Body: `{"detail": "Voice not found"}`.

---

### GET /voices/{voice_id}/sample

Download the paragraph audio as MP3 for this voice. Use this to listen before deciding to train a model from it.

**Path parameter:** `voice_id` – UUID of the voice.

**Response:** `200 OK` – Binary MP3 file.  
**Headers:** `Content-Type: audio/mpeg`

**Example (curl, save to file):**

```bash
curl -X GET "http://192.168.50.239:8000/voices/906f12d0-4a2b-4c3d-8e1f-123456789abc/sample" -o paragraph.mp3
```

**Example (Python, save to file):**

```python
r = requests.get(f"http://192.168.50.239:8000/voices/{voice_id}/sample")
r.raise_for_status()
with open("paragraph.mp3", "wb") as f:
    f.write(r.content)
```

**Errors:**

- `404 Not Found` – Voice not found or sample file missing.

---

### PATCH /voices/{voice_id}

Rename a voice. The new name must be unique.

**Path parameter:** `voice_id` – UUID of the voice.

**Request body:**

| Field  | Type   | Required | Description |
|--------|--------|----------|-------------|
| `name` | string | Yes      | New unique display name. |

**Example body:**

```json
{
  "name": "narrator_v2"
}
```

**Response:** `200 OK` – Updated voice object (with new `name`).

**Example (curl):**

```bash
curl -X PATCH "http://192.168.50.239:8000/voices/906f12d0-4a2b-4c3d-8e1f-123456789abc" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"narrator_v2\"}"
```

**Errors:**

- `400 Bad Request` – Empty name or name already used.
- `404 Not Found` – Voice not found.

---

### DELETE /voices/{voice_id}

Delete a voice and its paragraph WAV. Cannot be undone.

**Path parameter:** `voice_id` – UUID of the voice.

**Response:** `204 No Content` (empty body).

**Example (curl):**

```bash
curl -X DELETE "http://192.168.50.239:8000/voices/906f12d0-4a2b-4c3d-8e1f-123456789abc"
```

**Errors:**

- `404 Not Found` – Voice not found.

---

## Models

Models are CustomVoice checkpoints trained from a voice’s paragraph. Training runs in the background; you get a `model_id` immediately and poll until `status` is `ready` or `failed`.

### POST /models

Start training a new model from a voice. Returns immediately with a model ID; training continues in the background. Training can take several minutes.

**Request body:**

| Field      | Type   | Required | Description |
|-----------|--------|----------|-------------|
| `voice_id` | string | Yes      | ID of the voice to train from (must exist and have paragraph audio). |
| `name`     | string | No       | Display name for the model. Must be unique. If omitted, a default like `model_<id>` is used. |

**Example body:**

```json
{
  "voice_id": "906f12d0-4a2b-4c3d-8e1f-123456789abc",
  "name": "narrator_custom"
}
```

**Response:** `202 Accepted`

```json
{
  "model_id": "803be6ba-1a2b-3c4d-5e6f-789012345678",
  "status": "training",
  "message": "Poll GET /models/{model_id} for status."
}
```

**Example (curl):**

```bash
curl -X POST "http://192.168.50.239:8000/models" \
  -H "Content-Type: application/json" \
  -d "{\"voice_id\": \"906f12d0-4a2b-4c3d-8e1f-123456789abc\", \"name\": \"narrator_custom\"}"
```

**Example (Python, then poll for ready):**

```python
r = requests.post(
    "http://192.168.50.239:8000/models",
    json={"voice_id": voice_id, "name": "narrator_custom"},
)
r.raise_for_status()
assert r.status_code == 202
data = r.json()
model_id = data["model_id"]

# Poll until ready or failed
import time
while True:
    m = requests.get(f"http://192.168.50.239:8000/models/{model_id}").json()
    status = m.get("status")
    if status == "ready":
        break
    if status == "failed":
        raise RuntimeError("Training failed:", m.get("error"))
    time.sleep(10)
```

**Errors:**

- `400 Bad Request` – Model name already in use.
- `404 Not Found` – Voice not found.

---

### GET /models

List all models (including those still training or failed).

**Request:** No body.

**Response:** `200 OK` – JSON array of model objects. Each has at least: `id`, `name`, `voice_id`, `status` (`"training"`, `"ready"`, or `"failed"`), `created_at`. When `status` is `ready`, it also has `model_path`, `speaker_name`, `sample_path`.

**Example (curl):**

```bash
curl -X GET "http://192.168.50.239:8000/models"
```

---

### GET /models/{model_id}

Get one model by ID. Use this to poll status after POST /models.

**Path parameter:** `model_id` – UUID of the model.

**Response:** `200 OK` – Single model object.

**Example (training):**

```json
{
  "id": "803be6ba-1a2b-3c4d-5e6f-789012345678",
  "name": "narrator_custom",
  "voice_id": "906f12d0-4a2b-4c3d-8e1f-123456789abc",
  "status": "training",
  "created_at": "2026-02-04T12:05:00.000000Z"
}
```

**Example (ready):**

```json
{
  "id": "803be6ba-1a2b-3c4d-5e6f-789012345678",
  "name": "narrator_custom",
  "voice_id": "906f12d0-4a2b-4c3d-8e1f-123456789abc",
  "status": "ready",
  "model_path": "/path/to/checkpoint",
  "speaker_name": "narrator_custom",
  "sample_path": "/path/to/sample.wav",
  "created_at": "2026-02-04T12:05:00.000000Z"
}
```

**Errors:**

- `404 Not Found` – Model not found.

---

### GET /models/{model_id}/sample

Download the sample sentence audio as MP3 for a **ready** model. Use this to preview the trained voice before using it in synthesis.

**Path parameter:** `model_id` – UUID of the model.

**Response:** `200 OK` – Binary MP3 file.  
**Headers:** `Content-Type: audio/mpeg`

**Example (curl):**

```bash
curl -X GET "http://192.168.50.239:8000/models/803be6ba-1a2b-3c4d-5e6f-789012345678/sample" -o model_sample.mp3
```

**Errors:**

- `404 Not Found` – Model not found or sample file missing.
- `409 Conflict` – Model still training or training failed. Body: `{"detail": "Model still training"}` or `{"detail": "Model training failed"}`.

---

### PATCH /models/{model_id}

Rename a model (display name only). The internal speaker name used for synthesis does not change.

**Path parameter:** `model_id` – UUID of the model.

**Request body:**

| Field  | Type   | Required | Description |
|--------|--------|----------|-------------|
| `name` | string | Yes      | New unique display name. |

**Example body:**

```json
{
  "name": "narrator_final"
}
```

**Response:** `200 OK` – Updated model object.

**Errors:**

- `400 Bad Request` – Empty name or name already used.
- `404 Not Found` – Model not found.

---

### DELETE /models/{model_id}

Delete a model and its checkpoint and sample files. Cannot be undone.

**Path parameter:** `model_id` – UUID of the model.

**Response:** `204 No Content` (empty body).

**Example (curl):**

```bash
curl -X DELETE "http://192.168.50.239:8000/models/803be6ba-1a2b-3c4d-5e6f-789012345678"
```

**Errors:**

- `404 Not Found` – Model not found.

---

## Synthesize

Generate speech as MP3. You must choose exactly one: a voice (VoiceDesign), a trained model (CustomVoice), or the default (VoiceDesign with no instruction).

### POST /synthesize

Generate speech from text. Returns an MP3 file.

**Request body:**

| Field       | Type    | Required | Description |
|------------|---------|----------|-------------|
| `text`     | string  | Yes      | Text to speak. |
| `voice_id` | string  | No*      | Use this voice (VoiceDesign). |
| `model_id` | string  | No*      | Use this trained model (CustomVoice). |
| `use_default` | boolean | No*   | If `true`, use default VoiceDesign with no instruction. |

*Exactly one of `voice_id`, `model_id`, or `use_default: true` must be provided.

**Example (default voice):**

```json
{
  "text": "Hello, this is the default voice.",
  "use_default": true
}
```

**Example (specific voice):**

```json
{
  "text": "Hello, this is my custom narrator.",
  "voice_id": "906f12d0-4a2b-4c3d-8e1f-123456789abc"
}
```

**Example (trained model):**

```json
{
  "text": "Hello, this is my trained model.",
  "model_id": "803be6ba-1a2b-3c4d-5e6f-789012345678"
}
```

**Response:** `200 OK` – Binary MP3 file.  
**Headers:** `Content-Type: audio/mpeg`

**Example (curl, save to file):**

```bash
curl -X POST "http://192.168.50.239:8000/synthesize" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"Hello world.\", \"use_default\": true}" \
  -o output.mp3
```

**Example (Python, save to file):**

```python
r = requests.post(
    "http://192.168.50.239:8000/synthesize",
    json={"text": "Hello world.", "use_default": True},
)
r.raise_for_status()
with open("output.mp3", "wb") as f:
    f.write(r.content)
```

**Example (JavaScript, play in browser):**

```javascript
const res = await fetch('http://192.168.50.239:8000/synthesize', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ text: 'Hello world.', use_default: true }),
});
const blob = await res.blob();
const url = URL.createObjectURL(blob);
const audio = new Audio(url);
audio.play();
```

**Errors:**

- `400 Bad Request` – More than one of voice_id, model_id, use_default provided, or none of them. Body: `{"detail": "Specify one of voice_id, model_id, or use_default=true"}`.
- `404 Not Found` – Voice or model not found. Body: `{"detail": "Voice not found"}` or similar.

---

## Error responses

All errors return a JSON body with a `detail` field (string or object).

| Status | Meaning |
|--------|---------|
| `400` | Bad request (validation, duplicate name, wrong parameters). |
| `404` | Resource not found (voice, model, or sample file). |
| `409` | Conflict (e.g. model sample requested while still training). |

**Example error body:**

```json
{
  "detail": "Voice not found"
}
```

---

## Integration tips

1. **Base URL:** Use an env var or config for the API base. This server runs at `http://192.168.50.239:8000`.
2. **Timeouts:** POST /voices and POST /synthesize can take 30–120 seconds; set timeouts to 120+ seconds.
3. **Model training:** After POST /models (202), poll GET /models/{model_id} every 10–30 seconds until `status` is `"ready"` or `"failed"`. Only call GET /models/{model_id}/sample when `status` is `"ready"`.
4. **Saving audio:** All audio endpoints return MP3 bytes. Write them to a `.mp3` file or pass to an audio player; no extra parsing needed.
5. **Names:** Voice and model names must be unique. Handle 400 and show a clear message if the name is taken.
6. **Interactive docs:** Open `http://192.168.50.239:8000/docs` in a browser to try endpoints from the Swagger UI.
