#!/usr/bin/env python3
import base64
import json
import hashlib
import hmac
import os
import queue
import re
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from gpu45_resource import acquire_lease

UPSTREAM = "http://127.0.0.1:30000"
MAX_STORED_RESPONSES = 200
MAX_IDENTICAL_TOOL_CALLS = 5
SSE_HEARTBEAT_SECONDS = float(os.environ.get("GPU45_SSE_HEARTBEAT_SECONDS", "10"))
RESPONSE_STORE = {}
DB_PATH = os.environ.get("GPU45_DB_PATH", "/opt/gpu45-provider-appliance/prisma/dev.db")
PROFILE_PATH = os.environ.get("GPU45_PROFILE_PATH", "/etc/gpu45/provider-profile.json")
PROVIDER_SERVICE = os.environ.get("GPU45_PROVIDER_SERVICE", "llama-openai.service")
MODEL_REQUEST_LOCK = threading.RLock()
LLM_IDLE_SECONDS = float(os.environ.get("GPU45_LLM_IDLE_SECONDS", "120"))
LLM_IDLE_LOCK = threading.Lock()
LLM_IDLE_TIMER = None
LLM_IDLE_GENERATION = 0
COMPACTION_ENVELOPE_PREFIX = "gpu45c1."
COMPACTION_INSTRUCTION = """Create a compact continuation state for the conversation above.

Preserve every fact needed to continue the work correctly: the user's active request and preferences, decisions, constraints, exact identifiers and paths, completed work, current state, failures and diagnoses, pending work, and any tool results that matter. Discard repetition and conversational filler. Do not answer the user's request or call tools. Return only the continuation summary in plain text."""


def cancel_llm_idle_unload():
    global LLM_IDLE_TIMER, LLM_IDLE_GENERATION
    with LLM_IDLE_LOCK:
        LLM_IDLE_GENERATION += 1
        if LLM_IDLE_TIMER is not None:
            LLM_IDLE_TIMER.cancel()
            LLM_IDLE_TIMER = None


def unload_llm_after_idle(generation):
    global LLM_IDLE_TIMER
    with LLM_IDLE_LOCK:
        if generation != LLM_IDLE_GENERATION:
            return
        LLM_IDLE_TIMER = None
    if not MODEL_REQUEST_LOCK.acquire(blocking=False):
        with LLM_IDLE_LOCK:
            if generation == LLM_IDLE_GENERATION:
                LLM_IDLE_TIMER = threading.Timer(5, unload_llm_after_idle, args=(generation,))
                LLM_IDLE_TIMER.daemon = True
                LLM_IDLE_TIMER.start()
        return
    try:
        with LLM_IDLE_LOCK:
            if generation != LLM_IDLE_GENERATION:
                return
        subprocess.run(["systemctl", "stop", PROVIDER_SERVICE], check=False, timeout=30)
        print(f"stopped {PROVIDER_SERVICE} after {LLM_IDLE_SECONDS:g}s idle", flush=True)
    finally:
        MODEL_REQUEST_LOCK.release()


def schedule_llm_idle_unload():
    global LLM_IDLE_TIMER, LLM_IDLE_GENERATION
    with LLM_IDLE_LOCK:
        LLM_IDLE_GENERATION += 1
        generation = LLM_IDLE_GENERATION
        if LLM_IDLE_TIMER is not None:
            LLM_IDLE_TIMER.cancel()
        LLM_IDLE_TIMER = threading.Timer(LLM_IDLE_SECONDS, unload_llm_after_idle, args=(generation,))
        LLM_IDLE_TIMER.daemon = True
        LLM_IDLE_TIMER.start()


@contextmanager
def db_connect():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def is_primary_model(name):
    normalized = Path(name).name.lower()
    if "mmproj" in normalized:
        return False
    return re.search(r"^(mtp|draft)([-_.]|$)", normalized) is None


def endpoint_settings():
    with db_connect() as db:
        row = db.execute("SELECT allowAnonymous FROM EndpointSetting WHERE id = 'default'").fetchone()
    return {"allow_anonymous": bool(row["allowAnonymous"]) if row else True}


def authenticate(headers):
    settings = endpoint_settings()
    authorization = headers.get("Authorization", "")
    raw_key = headers.get("X-API-Key", "")
    if authorization.lower().startswith("bearer "):
        raw_key = authorization[7:].strip()
    if not raw_key:
        return (None, None) if settings["allow_anonymous"] else (None, "API key required")
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    with db_connect() as db:
        row = db.execute("SELECT * FROM ApiKey WHERE keyHash = ?", (key_hash,)).fetchone()
    if not row:
        if settings["allow_anonymous"]:
            return None, None
        return None, "Invalid API key"
    if row["suspendedAt"]:
        return None, "API key is suspended"
    if row["expiresAt"]:
        try:
            expires_at = datetime.fromisoformat(str(row["expiresAt"]).replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                return None, "API key has expired"
        except ValueError:
            return None, "API key has an invalid expiration date"
    return dict(row), None


def visible_models():
    with db_connect() as db:
        rows = db.execute(
            "SELECT path, name, servedAlias, defaultModel, active FROM ModelAsset WHERE served = 1 ORDER BY defaultModel DESC, name"
        ).fetchall()
    return [dict(row) for row in rows if row["servedAlias"] and is_primary_model(row["name"])]


def model_metadata(model):
    context_window = 262144
    try:
        with db_connect() as db:
            row = db.execute(
                """
                SELECT ctxSize
                FROM LaunchProfile
                WHERE modelPath = ?
                ORDER BY active DESC, updatedAt DESC
                LIMIT 1
                """,
                (model["path"],),
            ).fetchone()
        if row and row["ctxSize"]:
            context_window = int(row["ctxSize"])
    except Exception:
        pass

    return {
        "id": model["servedAlias"],
        "object": "model",
        "owned_by": "gpu45",
        "context_window": context_window,
        "max_context_window": context_window,
        "effective_context_window_percent": 95,
    }


def read_profile():
    try:
        return json.loads(Path(PROFILE_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_model(requested_model):
    models = visible_models()
    requested = str(requested_model or "").strip()
    selected = next((model for model in models if model["servedAlias"] == requested), None)
    if selected:
        return selected
    active_path = read_profile().get("modelPath")
    with db_connect() as db:
        active = db.execute("SELECT path, name, servedAlias, defaultModel, active FROM ModelAsset WHERE path = ?", (active_path,)).fetchone()
        if active and is_primary_model(active["name"]):
            return dict(active)
        fallback = db.execute(
            "SELECT path, name, servedAlias, defaultModel, active FROM ModelAsset WHERE defaultModel = 1 LIMIT 1"
        ).fetchone()
    return dict(fallback) if fallback else (models[0] if models else None)


def model_companions(db, model_path):
    directory = str(Path(model_path).parent)
    rows = db.execute("SELECT path, name FROM ModelAsset").fetchall()
    siblings = [row for row in rows if str(Path(row["path"]).parent) == directory and row["path"] != model_path]
    draft = next((row["path"] for row in siblings if not is_primary_model(row["name"]) and "mmproj" not in row["name"].lower()), None)
    projector = next((row["path"] for row in siblings if "mmproj" in row["name"].lower()), None)
    stored = db.execute("SELECT draftPath, projectorPath FROM ModelAsset WHERE path = ?", (model_path,)).fetchone()
    if stored:
        draft = stored["draftPath"] or draft
        projector = stored["projectorPath"] or projector
    profile = db.execute("SELECT modelDraftPath, mmprojPath FROM LaunchProfile WHERE modelPath = ? ORDER BY updatedAt DESC LIMIT 1", (model_path,)).fetchone()
    if profile:
        draft = profile["modelDraftPath"] or draft
        projector = profile["mmprojPath"] or projector
    return draft, projector


def model_launch_profile(db, model_path):
    return db.execute(
        """
        SELECT host, port, ctxSize, gpuLayers, batchSize, uBatchSize, cacheRamMiB,
               cacheTypeK, cacheTypeV, cacheReuse, specType, specDraftNMax,
               flashAttention, imageMinTokens, metrics, jinja
        FROM LaunchProfile
        WHERE modelPath = ?
        ORDER BY active DESC, updatedAt DESC
        LIMIT 1
        """,
        (model_path,),
    ).fetchone()


def apply_launch_profile_settings(next_profile, launch_profile):
    if not launch_profile:
        return
    for key in (
        "host",
        "port",
        "ctxSize",
        "gpuLayers",
        "batchSize",
        "uBatchSize",
        "cacheRamMiB",
        "cacheTypeK",
        "cacheTypeV",
        "cacheReuse",
        "specType",
        "specDraftNMax",
        "flashAttention",
        "imageMinTokens",
    ):
        value = launch_profile[key]
        if value is not None:
            next_profile[key] = value
    for key in ("metrics", "jinja"):
        value = launch_profile[key]
        if value is not None:
            next_profile[key] = bool(value)


def wait_for_backend(timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{UPSTREAM}/v1/models", timeout=3) as response:
                if response.status == 200:
                    return True
        except (OSError, urllib.error.URLError):
            time.sleep(2)
    return False


def ensure_model_loaded(model):
    current = read_profile()
    with db_connect() as db:
        if current.get("modelPath"):
            db.execute(
                "UPDATE ModelAsset SET draftPath = COALESCE(?, draftPath), projectorPath = COALESCE(?, projectorPath) WHERE path = ?",
                (current.get("modelDraftPath"), current.get("mmprojPath"), current.get("modelPath")),
            )
            db.commit()
        draft, projector = model_companions(db, model["path"])
        launch_profile = model_launch_profile(db, model["path"])

    next_profile = dict(current)
    apply_launch_profile_settings(next_profile, launch_profile)
    next_profile["specType"] = next_profile.get("specType") or (
        "draft-mtp" if draft or "mtp" in str(Path(model["path"]).parent).lower() else "none"
    )
    next_profile.update({
        "name": model["servedAlias"],
        "alias": model["servedAlias"],
        "description": model["name"],
        "modelPath": model["path"],
        "modelDraftPath": draft,
        "mmprojPath": projector,
    })

    restart_keys = (
        "modelPath",
        "alias",
        "modelDraftPath",
        "mmprojPath",
        "batchSize",
        "uBatchSize",
        "cacheTypeK",
        "cacheTypeV",
        "specDraftNMax",
        "specType",
        "flashAttention",
    )
    if all(current.get(key) == next_profile.get(key) for key in restart_keys):
        active = subprocess.run(["systemctl", "is-active", "--quiet", PROVIDER_SERVICE], check=False).returncode == 0
        if not active:
            subprocess.run(["systemctl", "start", PROVIDER_SERVICE], check=True, timeout=30)
        return

    profile_path = Path(PROFILE_PATH)
    temporary = profile_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(next_profile, indent=2) + "\n", encoding="utf-8")
    temporary.replace(profile_path)
    subprocess.run(["systemctl", "restart", PROVIDER_SERVICE], check=True, timeout=30)
    if not wait_for_backend():
        profile_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        subprocess.run(["systemctl", "restart", PROVIDER_SERVICE], check=False, timeout=30)
        raise RuntimeError(f"Model {model['servedAlias']} did not become ready")
    with db_connect() as db:
        db.execute("UPDATE ModelAsset SET active = 0")
        db.execute("UPDATE ModelAsset SET active = 1 WHERE path IN (?, ?, ?)", (model["path"], draft or "", projector or ""))
        db.commit()


def usage_tokens(response):
    usage = response.get("usage", {}) if isinstance(response, dict) else {}
    return int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0), int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)


def record_usage(api_key_id, model, requested_model, status_code, response=None):
    prompt_tokens, completion_tokens = usage_tokens(response or {})
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    with db_connect() as db:
        db.execute(
            "INSERT INTO ApiKeyUsage (id, apiKeyId, model, requestedModel, promptTokens, completionTokens, statusCode, createdAt) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, api_key_id, model or "unknown", requested_model, prompt_tokens, completion_tokens, status_code, now),
        )
        if api_key_id:
            db.execute(
                "UPDATE ApiKey SET lastUsedAt = ?, requestCount = requestCount + 1, promptTokens = promptTokens + ?, completionTokens = completionTokens + ? WHERE id = ?",
                (now, prompt_tokens, completion_tokens, api_key_id),
            )
        db.commit()


def flatten_namespace_tools(body):
    """Translate Codex namespace tools into llama.cpp-compatible functions."""
    tools = body.get("tools")
    if not isinstance(tools, list):
        return body, {}

    flattened = []
    name_map = {}
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "namespace":
            flattened.append(tool)
            continue

        namespace = str(tool.get("name", ""))
        namespace_description = str(tool.get("description", "")).strip()
        for inner in tool.get("tools", []):
            if not isinstance(inner, dict) or inner.get("type") != "function":
                continue
            inner_name = str(inner.get("name", ""))
            if not namespace or not inner_name:
                continue
            flat_name = f"{namespace}{inner_name}" if namespace.endswith("__") else f"{namespace}__{inner_name}"
            flattened_tool = dict(inner)
            flattened_tool["type"] = "function"
            flattened_tool["name"] = flat_name
            if namespace_description and flattened_tool.get("description"):
                flattened_tool["description"] = (
                    f"{namespace_description} {flattened_tool['description']}"
                )
            elif namespace_description:
                flattened_tool["description"] = namespace_description
            flattened.append(flattened_tool)
            name_map[flat_name] = (namespace, inner_name)

    if not name_map:
        return body, {}
    normalized = dict(body)
    normalized["tools"] = flattened
    return normalized, name_map


def restore_namespaced_calls(value, name_map):
    """Restore the namespace/name split Codex's tool router requires."""
    if isinstance(value, list):
        return [restore_namespaced_calls(item, name_map) for item in value]
    if not isinstance(value, dict):
        return value

    restored = {
        key: restore_namespaced_calls(item, name_map)
        for key, item in value.items()
    }
    if restored.get("type") == "function_call":
        mapping = name_map.get(restored.get("name"))
        if mapping:
            restored["namespace"], restored["name"] = mapping
    return restored


def flatten_namespaced_calls(value, name_map):
    """Flatten namespaced function_call input items before sending to llama.cpp."""
    if isinstance(value, list):
        return [flatten_namespaced_calls(item, name_map) for item in value]
    if not isinstance(value, dict):
        return value

    flattened = {
        key: flatten_namespaced_calls(item, name_map)
        for key, item in value.items()
    }
    if flattened.get("type") == "function_call" and flattened.get("namespace"):
        target = (flattened.get("namespace"), flattened.get("name"))
        flat_name = next(
            (name for name, mapping in name_map.items() if mapping == target),
            None,
        )
        if flat_name:
            flattened["name"] = flat_name
            flattened.pop("namespace", None)
    return flattened


def normalize_tool_output_items(value):
    """Move tool-result images into user messages that llama.cpp can parse."""
    if not isinstance(value, list):
        return value

    normalized = []
    for item in value:
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            normalized.append(item)
            continue

        output = item.get("output")
        if not isinstance(output, list):
            normalized.append(item)
            continue

        texts = []
        images = []
        for block in output:
            if not isinstance(block, dict):
                texts.append(str(block))
                continue
            block_type = block.get("type")
            if block_type in {"input_text", "text", "output_text"} and block.get("text"):
                texts.append(str(block["text"]))
            elif block_type == "input_image" and block.get("image_url"):
                images.append(block)

        text_output = "\n".join(texts).strip() or "Tool completed without text output."
        normalized.append({**item, "output": text_output})
        if images:
            normalized.append(
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Visual output for tool call {item.get('call_id')}:",
                        },
                        *images,
                    ],
                }
            )
    return normalized


def normalize_system_messages(value):
    """Keep system/developer instructions at the front for strict Jinja templates."""
    if not isinstance(value, list):
        return value

    instruction_parts = []
    remainder = []
    for item in value:
        if (
            isinstance(item, dict)
            and item.get("type") == "message"
            and item.get("role") in {"system", "developer"}
        ):
            text = text_from_input(item.get("content"))
            if text:
                role = item.get("role")
                instruction_parts.append(f"{role}:\n{text}" if role == "developer" else text)
            continue
        remainder.append(item)

    if not instruction_parts:
        return value

    return [
        {
            "type": "message",
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": "\n\n".join(instruction_parts),
                }
            ],
        },
        *remainder,
    ]



def prepend_system_text(body, text):
    normalized = dict(body)
    current_input = normalized.get("input")
    if isinstance(current_input, list):
        input_items = current_input
    elif isinstance(current_input, str):
        input_items = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": current_input}],
            }
        ]
    elif current_input is None:
        input_items = []
    else:
        input_items = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(current_input, ensure_ascii=False)}],
            }
        ]
    normalized["input"] = [
        {
            "type": "message",
            "role": "system",
            "content": [{"type": "input_text", "text": text}],
        },
        *input_items,
    ]
    return normalized


def apply_model_behavior_hints(body):
    """Add small model-specific execution hints for open weights that over-explain."""
    model = str(body.get("model") or "").lower()
    tools = body.get("tools")
    if "gemma" not in model or not isinstance(tools, list) or not tools:
        return body
    hint = (
        "Gemma tool-use compatibility hint: when the user asks you to inspect files, "
        "search, run commands, open links, use browser/MCP resources, or otherwise take "
        "an external action, call the appropriate tool immediately. Do not merely say "
        "that you will do it. If a tool is needed, emit a tool call as the next action; "
        "after tool results are returned, continue from the result."
    )
    print(f"applied Gemma tool-use hint model={body.get('model')} tools={len(tools)}", flush=True)
    return prepend_system_text(body, hint)

def normalize_responses_instructions(body):
    """Move top-level Responses instructions into leading system input."""
    instructions = body.get("instructions")
    if not instructions:
        return body

    normalized = dict(body)
    normalized.pop("instructions", None)
    current_input = normalized.get("input")
    if isinstance(current_input, list):
        input_items = current_input
    elif isinstance(current_input, str):
        input_items = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": current_input}],
            }
        ]
    elif current_input is None:
        input_items = []
    else:
        input_items = [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": json.dumps(current_input, ensure_ascii=False),
                    }
                ],
            }
        ]

    normalized["input"] = [
        {
            "type": "message",
            "role": "system",
            "content": [
                {
                    "type": "input_text",
                    "text": str(instructions),
                }
            ],
        },
        *input_items,
    ]
    return normalized


def repeated_tool_call(value):
    """Return the repeated call signature and count at the end of a history."""
    if not isinstance(value, list):
        return None, 0

    calls = [
        item
        for item in value
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    if not calls:
        return None, 0

    last = calls[-1]
    name = str(last.get("name", ""))
    if name.lower() == "wait" or name.lower().endswith("__wait"):
        return None, 0

    signature = (name, str(last.get("arguments", "")))
    count = 0
    for call in reversed(calls):
        current = (str(call.get("name", "")), str(call.get("arguments", "")))
        if current != signature:
            break
        count += 1
    return signature, count


def apply_tool_loop_guard(body):
    """Force a text-only stop after too many identical tool requests."""
    signature, count = repeated_tool_call(body.get("input"))
    if count < MAX_IDENTICAL_TOOL_CALLS:
        return body, None

    guarded = dict(body)
    guarded["tools"] = []
    guarded.pop("tool_choice", None)
    guarded["parallel_tool_calls"] = False
    guarded_input = list(guarded.get("input") or [])
    guarded_input.append(
        {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Provider safety stop: the same tool call was requested "
                        f"{count} consecutive times. Do not call it again. Explain "
                        "that the repetition guard stopped execution and that the "
                        "workspace state must be re-read in a fresh turn before a "
                        "different action is chosen."
                    ),
                }
            ],
        }
    )
    guarded["input"] = guarded_input
    return guarded, {"name": signature[0], "count": count}


def prune_store():
    if len(RESPONSE_STORE) <= MAX_STORED_RESPONSES:
        return
    oldest = sorted(RESPONSE_STORE.items(), key=lambda item: item[1]["stored_at"])
    for response_id, _ in oldest[: len(RESPONSE_STORE) - MAX_STORED_RESPONSES]:
        RESPONSE_STORE.pop(response_id, None)


def text_from_input(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "message":
                    content = item.get("content")
                    if isinstance(content, str):
                        parts.append(content)
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                text = block.get("text") or block.get("input_text")
                                if text:
                                    parts.append(str(text))
                elif item.get("type") == "input_text" and item.get("text"):
                    parts.append(str(item["text"]))
        return "\n".join(parts)
    return json.dumps(value, ensure_ascii=False)


def compaction_secret():
    configured = os.environ.get("GPU45_COMPACTION_SECRET")
    if configured:
        return configured.encode("utf-8")
    try:
        machine_id = Path("/etc/machine-id").read_bytes().strip()
    except OSError:
        machine_id = b"gpu45-development-machine"
    return hashlib.sha256(b"gpu45-responses-compaction-v1\0" + machine_id).digest()


def _compaction_keystream(secret, nonce, length):
    output = bytearray()
    counter = 0
    while len(output) < length:
        output.extend(hmac.new(secret, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(output[:length])


def encode_compaction(summary):
    plaintext = json.dumps(
        {"version": 1, "summary": str(summary)}, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    secret = compaction_secret()
    nonce = os.urandom(16)
    stream = _compaction_keystream(secret, nonce, len(plaintext))
    ciphertext = bytes(left ^ right for left, right in zip(plaintext, stream))
    tag = hmac.new(secret, b"gpu45-compaction-v1\0" + nonce + ciphertext, hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii").rstrip("=")
    return COMPACTION_ENVELOPE_PREFIX + encoded


def decode_compaction(value):
    if not isinstance(value, str) or not value.startswith(COMPACTION_ENVELOPE_PREFIX):
        raise ValueError("Compaction state was not created by this GPU45 appliance")
    encoded = value[len(COMPACTION_ENVELOPE_PREFIX):]
    try:
        packed = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except Exception as exc:
        raise ValueError("Compaction state has invalid encoding") from exc
    if len(packed) < 49:
        raise ValueError("Compaction state is truncated")
    nonce, supplied_tag, ciphertext = packed[:16], packed[16:48], packed[48:]
    secret = compaction_secret()
    expected_tag = hmac.new(
        secret, b"gpu45-compaction-v1\0" + nonce + ciphertext, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(supplied_tag, expected_tag):
        raise ValueError("Compaction state failed integrity validation")
    stream = _compaction_keystream(secret, nonce, len(ciphertext))
    plaintext = bytes(left ^ right for left, right in zip(ciphertext, stream))
    try:
        envelope = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Compaction state payload is invalid") from exc
    if envelope.get("version") != 1 or not isinstance(envelope.get("summary"), str):
        raise ValueError("Compaction state version is unsupported")
    return envelope["summary"]


def has_compaction_trigger(value):
    return isinstance(value, list) and any(
        isinstance(item, dict) and item.get("type") == "compaction_trigger" for item in value
    )


def expand_compaction_items(value):
    if not isinstance(value, list):
        return value
    expanded = []
    for item in value:
        if isinstance(item, dict) and item.get("type") == "compaction":
            summary = decode_compaction(item.get("encrypted_content"))
            expanded.append({
                "type": "message",
                "role": "system",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "GPU45 compacted continuation state. Treat this as authoritative prior "
                        "conversation context:\n\n" + summary
                    ),
                }],
            })
        else:
            expanded.append(item)
    return expanded


def prepare_compaction_request(body):
    compact_request = dict(body)
    value = compact_request.get("input", [])
    if isinstance(value, str):
        items = [{
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": value}],
        }]
    elif isinstance(value, list):
        items = expand_compaction_items(value)
    else:
        items = []
    items = [
        item for item in items
        if not (isinstance(item, dict) and item.get("type") == "compaction_trigger")
    ]
    items.append({
        "type": "message",
        "role": "system",
        "content": [{"type": "input_text", "text": COMPACTION_INSTRUCTION}],
    })
    compact_request["input"] = items
    compact_request["tools"] = []
    compact_request["tool_choice"] = "none"
    compact_request["parallel_tool_calls"] = False
    compact_request["stream"] = True
    compact_request["max_output_tokens"] = min(int(body.get("max_output_tokens") or 8192), 8192)
    return compact_request


def output_text_from_response(response):
    parts = []
    for item in response.get("output", []) if isinstance(response, dict) else []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                parts.append(str(content.get("text", "")))
    return "\n".join(part for part in parts if part).strip()


def compaction_response(model, summary, usage=None):
    now = int(time.time())
    item = {
        "id": f"cmp_{uuid.uuid4().hex}",
        "type": "compaction",
        "encrypted_content": encode_compaction(summary),
    }
    response = {
        "id": f"resp_gpu45_cmp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": now,
        "completed_at": now,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "model": model,
        "output": [item],
        "usage": usage or {
            "input_tokens": 0,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 0,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 0,
        },
    }
    return response, item


def describe_output_items(items):
    lines = []
    for item in items or []:
        item_type = item.get("type") if isinstance(item, dict) else None
        if item_type == "function_call":
            qualified_name = item.get("name")
            if item.get("namespace"):
                qualified_name = f"{item['namespace']}{qualified_name}"
            lines.append(
                "Assistant requested tool call "
                f"{qualified_name} call_id={item.get('call_id')} "
                f"arguments={item.get('arguments')}"
            )
        elif item_type == "message":
            content = item.get("content", [])
            lines.append(f"Assistant message: {text_from_input(content)}")
        elif item_type == "reasoning":
            continue
        else:
            lines.append(f"Assistant output item: {json.dumps(item, ensure_ascii=False)}")
    return "\n".join(lines)


def tool_outputs_from_input(value):
    outputs = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and item.get("type") == "function_call_output":
                outputs.append(
                    f"Tool output for call_id={item.get('call_id')}:\n{item.get('output', '')}"
                )
    return "\n\n".join(outputs)


def build_followup_input(body):
    previous_id = body.get("previous_response_id")
    previous = RESPONSE_STORE.get(previous_id)
    current_input = body.get("input")
    if not previous:
        return current_input

    previous_request = previous.get("request", {})
    previous_response = previous.get("response", {})
    original_input = previous_request.get("input", [])
    if isinstance(original_input, str):
        original_input = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": original_input}],
            }
        ]
    elif not isinstance(original_input, list):
        original_input = []

    previous_outputs = [
        item
        for item in previous_response.get("output", [])
        if isinstance(item, dict) and item.get("type") != "reasoning"
    ]
    current_items = current_input if isinstance(current_input, list) else []
    return [*original_input, *previous_outputs, *current_items]


def store_response(request_body, response_body):
    if not isinstance(response_body, dict):
        return
    response_id = response_body.get("id")
    if not response_id:
        return
    RESPONSE_STORE[response_id] = {
        "stored_at": time.time(),
        "request": request_body,
        "response": response_body,
    }
    prune_store()


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("%s - - [%s] %s" % (self.address_string(), self.log_date_time_string(), fmt % args), flush=True)

    def do_GET(self):
        self.proxy()

    def do_POST(self):
        self.proxy()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization,content-type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_json(self, status, value):
        payload = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def proxy(self):
        path = urlparse(self.path).path
        api_key, auth_error = authenticate(self.headers)
        if auth_error:
            self.send_json(401, {"error": {"message": auth_error, "type": "authentication_error"}})
            return
        if self.command == "GET" and path in {"/models", "/v1/models"}:
            models = visible_models()
            metadata = [model_metadata(model) for model in models]
            self.send_json(200, {
                "object": "list",
                "data": metadata,
            })
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw_body = self.rfile.read(length) if length else b""
        request_body = None
        namespace_map = {}
        selected_model = None
        requested_model = None
        inference_request = self.command == "POST" and path.startswith("/v1/")
        lock_acquired = False
        resource_lease = None
        compaction_requested = False

        if self.command == "POST" and raw_body:
            try:
                request_body = json.loads(raw_body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_json(400, {"error": {"message": "Request body must be valid JSON", "type": "invalid_request_error"}})
                return
            requested_model = request_body.get("model")
            if inference_request:
                selected_model = resolve_model(requested_model)
                if not selected_model:
                    self.send_json(503, {"error": {"message": "No primary model is available", "type": "server_error"}})
                    return
                cancel_llm_idle_unload()
                MODEL_REQUEST_LOCK.acquire()
                lock_acquired = True
                if path != "/v1/responses":
                    try:
                        resource_lease = acquire_lease(f"codex-{uuid.uuid4().hex[:12]}", "llm", 100, False, "keep-loaded", timeout=600)
                        ensure_model_loaded(selected_model)
                    except Exception as exc:
                        if resource_lease is not None:
                            resource_lease.release()
                            resource_lease = None
                        MODEL_REQUEST_LOCK.release()
                        lock_acquired = False
                        self.send_json(503, {"error": {"message": str(exc), "type": "model_load_error"}})
                        record_usage(api_key["id"] if api_key else None, selected_model["servedAlias"], requested_model, 503)
                        return
                request_body["model"] = selected_model["servedAlias"]
                raw_body = json.dumps(request_body, ensure_ascii=False).encode("utf-8")

        if self.command == "POST" and path == "/v1/responses" and raw_body:
            compaction_requested = has_compaction_trigger(request_body.get("input"))
            if request_body.get("previous_response_id"):
                request_body = dict(request_body)
                request_body["input"] = build_followup_input(request_body)
                request_body.pop("previous_response_id", None)
            if compaction_requested:
                try:
                    request_body = prepare_compaction_request(request_body)
                except (TypeError, ValueError) as exc:
                    self.send_json(400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
                    if lock_acquired:
                        MODEL_REQUEST_LOCK.release()
                    return
            else:
                try:
                    request_body["input"] = expand_compaction_items(request_body.get("input"))
                except ValueError as exc:
                    self.send_json(400, {"error": {"message": str(exc), "type": "invalid_request_error"}})
                    if lock_acquired:
                        MODEL_REQUEST_LOCK.release()
                    return
            request_body = normalize_responses_instructions(request_body)
            request_body = apply_model_behavior_hints(request_body)
            request_body, namespace_map = flatten_namespace_tools(request_body)
            request_body["input"] = normalize_tool_output_items(
                flatten_namespaced_calls(request_body.get("input"), namespace_map)
            )
            request_body["input"] = normalize_system_messages(request_body.get("input"))
            request_body, loop_guard = apply_tool_loop_guard(request_body)
            if loop_guard:
                print(
                    "tool loop guard engaged: "
                    f"{loop_guard['name']} repeated {loop_guard['count']} times",
                    flush=True,
                )
            if namespace_map:
                print(f"flattened {len(namespace_map)} namespaced tools", flush=True)
            request_body["stream"] = True
            raw_body = json.dumps(request_body, ensure_ascii=False).encode("utf-8")

        upstream_url = UPSTREAM + self.path
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection", "accept-encoding", "authorization", "x-api-key"}
        }
        if self.command == "POST" and path == "/v1/responses":
            headers["Accept"] = "text/event-stream"

        req = urllib.request.Request(
            upstream_url,
            data=raw_body if self.command == "POST" else None,
            headers=headers,
            method=self.command,
        )

        usage_recorded = False
        try:
            if self.command == "POST" and path == "/v1/responses" and request_body and request_body.get("stream"):
                usage_recorded = self.proxy_responses_stream(
                    req,
                    request_body,
                    namespace_map,
                    api_key["id"] if api_key else None,
                    selected_model["servedAlias"] if selected_model else None,
                    requested_model,
                    compaction_requested,
                )
            else:
                usage_recorded = self.proxy_upstream_response(
                    req,
                    path,
                    request_body,
                    namespace_map,
                    api_key["id"] if api_key else None,
                    selected_model["servedAlias"] if selected_model else None,
                    requested_model,
                    inference_request,
                )
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() in {"connection", "transfer-encoding", "content-length", "content-encoding"}:
                    continue
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            if inference_request:
                record_usage(api_key["id"] if api_key else None, selected_model["servedAlias"] if selected_model else "unknown", requested_model, exc.code)
                usage_recorded = True
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.send_json(502, {"error": {"message": f"Upstream provider unavailable: {exc}", "type": "upstream_error"}})
            if inference_request:
                record_usage(api_key["id"] if api_key else None, selected_model["servedAlias"] if selected_model else "unknown", requested_model, 502)
                usage_recorded = True
        finally:
            if inference_request and not usage_recorded:
                record_usage(api_key["id"] if api_key else None, selected_model["servedAlias"] if selected_model else "unknown", requested_model, 499)
            if lock_acquired:
                MODEL_REQUEST_LOCK.release()
            if resource_lease is not None:
                resource_lease.release()
            if inference_request:
                schedule_llm_idle_unload()

    def proxy_upstream_response(self, req, path, request_body, namespace_map, api_key_id, model, requested_model, inference_request):
        with urllib.request.urlopen(req, timeout=600) as resp:
            content_type = resp.headers.get("Content-Type", "application/octet-stream")
            self.send_response(resp.status)
            for key, value in resp.headers.items():
                if key.lower() in {"connection", "transfer-encoding", "content-length", "content-encoding"}:
                    continue
                self.send_header(key, value)
            self.send_header("Access-Control-Allow-Origin", "*")

            if "text/event-stream" in content_type:
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                return self.stream_sse(resp, request_body, namespace_map, api_key_id, model, requested_model)

            payload = resp.read()
            response_body = None
            if path == "/v1/responses" and payload:
                try:
                    response_body = restore_namespaced_calls(
                        json.loads(payload.decode("utf-8")), namespace_map
                    )
                    payload = json.dumps(response_body, ensure_ascii=False).encode("utf-8")
                    store_response(request_body or {}, response_body)
                except Exception as exc:
                    print(f"response store skipped: {exc}", flush=True)
            if inference_request:
                record_usage(api_key_id, model or "unknown", requested_model, resp.status, response_body)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return bool(inference_request)

    def proxy_responses_stream(self, req, request_body, namespace_map, api_key_id, model, requested_model, compaction_requested=False):
        request_id = f"gpu45-{uuid.uuid4().hex[:12]}"
        started_at = time.time()
        input_size = len(json.dumps(request_body.get("input", ""), ensure_ascii=False))
        print(
            f"{request_id} accepted /v1/responses model={model or 'unknown'} "
            f"requested={requested_model or ''} stream=true input_json_chars={input_size}",
            flush=True,
        )

        upstream_events = queue.Queue()

        def read_upstream():
            stream_lease = None
            try:
                stream_lease = acquire_lease(f"codex-{request_id}", "llm", 100, False, "keep-loaded", timeout=600)
                selected = resolve_model(model)
                if not selected:
                    raise RuntimeError(f"Model is no longer available: {model}")
                ensure_model_loaded(selected)
                deadline = time.time() + 600
                while True:
                    try:
                        with urllib.request.urlopen(req, timeout=600) as resp:
                            content_type = resp.headers.get("Content-Type", "application/octet-stream")
                            upstream_events.put(("open", resp.status, content_type))
                            if "text/event-stream" in content_type:
                                event_lines = []
                                while True:
                                    line = resp.readline()
                                    if not line: break
                                    if line.strip(): event_lines.append(line.rstrip(b"\r\n")); continue
                                    upstream_events.put(("event", event_lines)); event_lines = []
                                if event_lines: upstream_events.put(("event", event_lines))
                            else:
                                upstream_events.put(("payload", resp.status, content_type, resp.read()))
                        break
                    except urllib.error.HTTPError as exc:
                        body = exc.read().decode("utf-8", "replace")
                        if exc.code == 503 and "loading model" in body.lower() and time.time() < deadline:
                            upstream_events.put(("waiting", "loading model")); time.sleep(5); continue
                        upstream_events.put(("http_error", exc.code, body)); break
                    except (urllib.error.URLError, ConnectionRefusedError, TimeoutError, OSError) as exc:
                        if time.time() < deadline:
                            upstream_events.put(("waiting", "backend starting")); time.sleep(5); continue
                        upstream_events.put(("error", repr(exc))); break
            except urllib.error.HTTPError as exc:
                upstream_events.put(("http_error", exc.code, exc.read().decode("utf-8", "replace")))
            except Exception as exc:
                upstream_events.put(("error", repr(exc)))
            finally:
                if stream_lease is not None:
                    stream_lease.release()
                upstream_events.put(("done",))

        thread = threading.Thread(target=read_upstream, name=f"{request_id}-upstream", daemon=True)
        thread.start()

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-GPU45-Request-ID", request_id)
        self.end_headers()

        completed = False
        upstream_opened = False
        upstream_completed_response = None
        try:
            self.write_sse_comment(f"{request_id} accepted")
            while True:
                try:
                    item = upstream_events.get(timeout=SSE_HEARTBEAT_SECONDS)
                except queue.Empty:
                    elapsed = int(time.time() - started_at)
                    phase = "prefill" if not upstream_opened else "generating"
                    self.write_sse_comment(f"{request_id} heartbeat phase={phase} elapsed_s={elapsed}")
                    continue

                kind = item[0]
                if kind == "open":
                    upstream_opened = True
                    elapsed_ms = int((time.time() - started_at) * 1000)
                    print(f"{request_id} upstream_open status={item[1]} content_type={item[2]} elapsed_ms={elapsed_ms}", flush=True)
                    self.write_sse_comment(f"{request_id} upstream_open elapsed_ms={elapsed_ms}")
                elif kind == "waiting":
                    elapsed = int(time.time() - started_at)
                    self.write_sse_comment(f"{request_id} waiting reason={item[1]} elapsed_s={elapsed}")
                elif kind == "event":
                    if compaction_requested:
                        response = self.parse_sse_response(item[1], namespace_map)
                    else:
                        response = self.write_sse_event(item[1], request_body, namespace_map)
                    if response and not completed:
                        if compaction_requested:
                            upstream_completed_response = response
                        else:
                            record_usage(api_key_id, model or "unknown", requested_model, 200, response)
                            completed = True
                elif kind == "payload":
                    status, content_type, payload = item[1], item[2], item[3]
                    response = None
                    if payload:
                        try:
                            response = restore_namespaced_calls(json.loads(payload.decode("utf-8")), namespace_map)
                            payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
                            store_response(request_body or {}, response)
                        except Exception:
                            pass
                    self.write_chunk(b"event: gpu45.payload\n")
                    self.write_chunk(b"data: " + payload + b"\n\n")
                    record_usage(api_key_id, model or "unknown", requested_model, status, response)
                    completed = True
                elif kind == "http_error":
                    code, message = item[1], item[2]
                    self.write_sse_error(code, message)
                    record_usage(api_key_id, model or "unknown", requested_model, code)
                    completed = True
                elif kind == "error":
                    self.write_sse_error(502, item[1])
                    record_usage(api_key_id, model or "unknown", requested_model, 502)
                    completed = True
                elif kind == "done":
                    if compaction_requested and not completed:
                        summary = output_text_from_response(upstream_completed_response)
                        if not summary:
                            self.write_sse_error(502, "GPU45 model returned no continuation summary")
                            record_usage(api_key_id, model or "unknown", requested_model, 502)
                        else:
                            response, compaction_item = compaction_response(
                                model or "unknown",
                                summary,
                                upstream_completed_response.get("usage"),
                            )
                            self.write_compaction_sse(response, compaction_item)
                            store_response(request_body or {}, response)
                            record_usage(api_key_id, model or "unknown", requested_model, 200, response)
                            completed = True
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                    self.close_connection = True
                    elapsed_ms = int((time.time() - started_at) * 1000)
                    print(f"{request_id} finished completed={completed} elapsed_ms={elapsed_ms}", flush=True)
                    return completed
        except (BrokenPipeError, ConnectionResetError):
            elapsed_ms = int((time.time() - started_at) * 1000)
            print(f"{request_id} downstream disconnected elapsed_ms={elapsed_ms}", flush=True)
            return completed

    def write_sse_comment(self, text):
        self.write_chunk(f": {text}\n\n".encode("utf-8"))

    def write_sse_error(self, status, message):
        payload = {
            "error": {
                "message": str(message),
                "type": "upstream_error",
                "code": status,
            }
        }
        self.write_chunk(b"event: error\n")
        self.write_chunk(b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\n")

    def write_sse_json_event(self, event):
        event_type = event.get("type", "message")
        self.write_chunk(f"event: {event_type}\n".encode("utf-8"))
        self.write_chunk(
            b"data: " + json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n\n"
        )

    def write_compaction_sse(self, response, item):
        in_progress = dict(response)
        in_progress.update({"status": "in_progress", "completed_at": None, "output": [], "usage": None})
        self.write_sse_json_event({
            "type": "response.created", "sequence_number": 0, "response": in_progress
        })
        self.write_sse_json_event({
            "type": "response.in_progress", "sequence_number": 1, "response": in_progress
        })
        self.write_sse_json_event({
            "type": "response.output_item.added",
            "sequence_number": 2,
            "output_index": 0,
            "item": item,
        })
        self.write_sse_json_event({
            "type": "response.output_item.done",
            "sequence_number": 3,
            "output_index": 0,
            "item": item,
        })
        self.write_sse_json_event({
            "type": "response.completed", "sequence_number": 4, "response": response
        })

    def write_chunk(self, data):
        if not data:
            return
        self.wfile.write(("%x\r\n" % len(data)).encode("ascii"))
        self.wfile.write(data)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def stream_sse(self, resp, request_body, namespace_map, api_key_id, model, requested_model):
        event_lines = []
        completed = False
        try:
            while True:
                line = resp.readline()
                if not line:
                    break
                if line.strip():
                    event_lines.append(line.rstrip(b"\r\n"))
                    continue
                response = self.write_sse_event(event_lines, request_body, namespace_map)
                if response and not completed:
                    record_usage(api_key_id, model or "unknown", requested_model, 200, response)
                    completed = True
                event_lines = []
            if event_lines:
                response = self.write_sse_event(event_lines, request_body, namespace_map)
                if response and not completed:
                    record_usage(api_key_id, model or "unknown", requested_model, 200, response)
                    completed = True
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            print("downstream client disconnected during SSE stream", flush=True)
        return completed

    def write_sse_event(self, lines, request_body, namespace_map):
        decoded = [line.decode("utf-8", "replace") for line in lines]
        data_lines = [line[5:].strip() for line in decoded if line.startswith("data:")]
        if not data_lines:
            for line in lines:
                self.write_chunk(line + b"\n")
            self.write_chunk(b"\n")
            return None
        data = "\n".join(data_lines)
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            for line in lines:
                self.write_chunk(line + b"\n")
            self.write_chunk(b"\n")
            return None
        event = restore_namespaced_calls(event, namespace_map)
        for line in decoded:
            if not line.startswith("data:"):
                self.write_chunk(line.encode("utf-8") + b"\n")
        self.write_chunk(
            b"data: " + json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n\n"
        )
        if event.get("type") == "response.completed" and isinstance(event.get("response"), dict):
            store_response(request_body or {}, event["response"])
            return event["response"]
        return None

    def parse_sse_response(self, lines, namespace_map):
        decoded = [line.decode("utf-8", "replace") for line in lines]
        data_lines = [line[5:].strip() for line in decoded if line.startswith("data:")]
        if not data_lines:
            return None
        try:
            event = restore_namespaced_calls(
                json.loads("\n".join(data_lines)), namespace_map
            )
        except json.JSONDecodeError:
            return None
        if event.get("type") == "response.completed" and isinstance(event.get("response"), dict):
            return event["response"]
        return None


def main():
    server = ThreadingHTTPServer(("0.0.0.0", 30001), ProxyHandler)
    print("gpu45 responses proxy listening on 0.0.0.0:30001 -> 127.0.0.1:30000", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
