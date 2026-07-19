from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


HOST = os.environ.get("GPU45_CODEX_PROXY_HOST", "127.0.0.1")
DOCKER_HOST = os.environ.get("GPU45_CODEX_PROXY_DOCKER_HOST", "").strip()
PORT = int(os.environ.get("GPU45_CODEX_PROXY_PORT", "30003"))
CODEX_BIN = os.environ.get("GPU45_CODEX_BIN") or shutil.which("codex") or "/usr/bin/codex"
CODEX_HOME = Path(os.environ.get("GPU45_CODEX_HOME", "/var/lib/gpu45-benchmark/.codex"))
WORK_ROOT = Path(os.environ.get("GPU45_CODEX_WORK_ROOT", "/var/lib/gpu45-benchmark/codex-reference"))
MODEL = os.environ.get("GPU45_CODEX_MODEL", "gpt-5.6-sol")
EFFORT = os.environ.get("GPU45_CODEX_REASONING_EFFORT", "medium")
REQUEST_TIMEOUT = int(os.environ.get("GPU45_CODEX_REQUEST_TIMEOUT", "900"))
AGENTIC_URL = os.environ.get("GPU45_AGENTIC_URL", "http://127.0.0.1:8055").rstrip("/")
AGENTIC_TOKEN = os.environ.get("GPU45_AGENTIC_TOKEN", "")
RUN_LOCK = threading.Lock()

CORRELATION_HEADERS = {
    "campaign_id": "X-GPU45-Benchmark-Campaign",
    "run_id": "X-GPU45-Benchmark-Run",
    "task_id": "X-GPU45-Benchmark-Task",
    "attempt": "X-GPU45-Benchmark-Attempt",
}

TURN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "content": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments_json": {"type": "string"},
                },
                "required": ["name", "arguments_json"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["content", "tool_calls"],
    "additionalProperties": False,
}


def listener_hosts(primary: str, docker_host: str = "") -> list[str]:
    return list(dict.fromkeys(host for host in (primary.strip(), docker_host.strip()) if host))


def build_turn_prompt(body: dict[str, Any]) -> str:
    messages = body.get("messages") if isinstance(body.get("messages"), list) else []
    tools = body.get("tools") if isinstance(body.get("tools"), list) else []
    tool_choice = body.get("tool_choice", "auto")
    return (
        "You are the target assistant for one turn of a controlled agent benchmark. "
        "Do not execute shell commands, browse, edit files, or call your built-in tools. "
        "Use only the conversation and benchmark function definitions below. Return one assistant turn through the required JSON schema. "
        "When a benchmark function should be called, leave content empty and add each requested call to tool_calls. "
        "arguments_json must be a valid compact JSON object string using the exact parameter names and types. "
        "When no function should be called, return the assistant answer in content and an empty tool_calls array. "
        "Never invent an unavailable function. Preserve parallel calls when the request needs independent functions.\n\n"
        f"TOOL_CHOICE_JSON\n{json.dumps(tool_choice, ensure_ascii=False, separators=(',', ':'))}\n\n"
        f"TOOLS_JSON\n{json.dumps(tools, ensure_ascii=False, separators=(',', ':'))}\n\n"
        f"CONVERSATION_JSON\n{json.dumps(messages, ensure_ascii=False, separators=(',', ':'))}"
    )


def parse_codex_jsonl(text: str) -> tuple[dict[str, Any], dict[str, int]]:
    final_text: str | None = None
    usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    failure: str | None = None
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                final_text = item["text"]
        elif event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage.update({key: int(event["usage"].get(key, 0) or 0) for key in usage})
        elif event.get("type") in {"error", "turn.failed"}:
            failure = str(event.get("message") or (event.get("error") or {}).get("message") or "Codex turn failed")
    if final_text is None:
        raise RuntimeError(failure or "Codex produced no final agent message")
    try:
        result = json.loads(final_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Codex final message was not valid structured JSON: {exc}") from exc
    if not isinstance(result, dict) or not isinstance(result.get("content"), str) or not isinstance(result.get("tool_calls"), list):
        raise RuntimeError("Codex structured output did not match the reference-turn contract")
    return result, usage


def build_chat_response(result: dict[str, Any], usage: dict[str, int], model: str) -> dict[str, Any]:
    tool_calls = []
    for item in result.get("tool_calls", []):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        arguments = str(item.get("arguments_json") or "{}")
        try:
            parsed = json.loads(arguments)
            if not isinstance(parsed, dict):
                raise ValueError("arguments must be an object")
            arguments = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        except (json.JSONDecodeError, ValueError):
            pass
        tool_calls.append({
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {"name": str(item["name"]), "arguments": arguments},
        })
    prompt_tokens = int(usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("output_tokens") or 0)
    reasoning_tokens = int(usage.get("reasoning_output_tokens") or 0)
    return {
        "id": f"chatcmpl-codex-{uuid.uuid4().hex[:20]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "system_fingerprint": "gpu45-codex-reference",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None if tool_calls else result.get("content", ""),
                **({"tool_calls": tool_calls} if tool_calls else {}),
            },
            "finish_reason": "tool_calls" if tool_calls else "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens_details": {"cached_tokens": int(usage.get("cached_input_tokens") or 0)},
            "completion_tokens_details": {"reasoning_tokens": reasoning_tokens},
        },
    }


def codex_environment() -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(CODEX_HOME)
    return env


def auth_status() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [CODEX_BIN, "-c", f'model_reasoning_effort="{EFFORT}"', "login", "status"],
            env=codex_environment(), capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    message = (result.stdout or result.stderr).strip()
    return result.returncode == 0 and "Logged in" in message, message


def run_codex_turn(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int], int]:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    prompt = build_turn_prompt(body)
    with tempfile.NamedTemporaryFile("w", suffix=".json", dir=WORK_ROOT, encoding="utf-8", delete=False) as schema_file:
        json.dump(TURN_SCHEMA, schema_file, separators=(",", ":"))
        schema_path = Path(schema_file.name)
    command = [
        CODEX_BIN, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
        "-m", MODEL, "-c", f'model_reasoning_effort="{EFFORT}"', "--sandbox", "read-only",
        "--output-schema", str(schema_path), "--json", "-",
    ]
    started = time.monotonic()
    try:
        with RUN_LOCK:
            result = subprocess.run(
                command, input=prompt, cwd=WORK_ROOT, env=codex_environment(), capture_output=True,
                text=True, timeout=REQUEST_TIMEOUT, check=False,
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        parsed, usage = parse_codex_jsonl(result.stdout)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-4000:])
        return parsed, usage, duration_ms
    finally:
        schema_path.unlink(missing_ok=True)


def correlation(headers: Any) -> dict[str, Any] | None:
    values = {key: str(headers.get(header, "")).strip() for key, header in CORRELATION_HEADERS.items()}
    if not all(values.values()):
        return None
    try:
        values["attempt"] = int(values["attempt"])
    except (TypeError, ValueError):
        return None
    return values if values["attempt"] > 0 else None


def submit_metric(headers: Any, requested_model: str, response: dict[str, Any] | None, status: int, duration_ms: int) -> None:
    context = correlation(headers)
    if not context or not AGENTIC_TOKEN:
        return
    usage = (response or {}).get("usage") or {}
    choices = (response or {}).get("choices") or []
    tool_calls = sum(
        len(((choice.get("message") or {}).get("tool_calls") or []))
        for choice in choices if isinstance(choice, dict)
    )
    details = usage.get("completion_tokens_details") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    payload = {
        "campaignId": context["campaign_id"], "runId": context["run_id"], "taskId": context["task_id"],
        "attempt": context["attempt"], "requestId": uuid.uuid4().hex, "apiPath": "/v1/chat/completions",
        "model": MODEL, "requestedModel": requested_model, "statusCode": status,
        "promptTokens": int(usage.get("prompt_tokens") or 0),
        "completionTokens": int(usage.get("completion_tokens") or 0),
        "cachedTokens": int(prompt_details.get("cached_tokens") or 0),
        "reasoningTokens": int(details.get("reasoning_tokens") or 0),
        "durationMs": duration_ms, "toolCalls": tool_calls, "usageSource": "codex_jsonl" if response else "missing",
        "completed": 200 <= status < 300,
    }
    request = urllib.request.Request(
        AGENTIC_URL + "/v1/metrics/requests", data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Authorization": f"Bearer {AGENTIC_TOKEN}", "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as result:
            result.read()
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        print(f"codex-reference metric submission failed: {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "GPU45CodexReference/1.0"

    def log_message(self, message: str, *args: object) -> None:
        print(f"codex-reference: {message % args}", flush=True)

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            authenticated, detail = auth_status()
            self.send_json(HTTPStatus.OK if authenticated else HTTPStatus.SERVICE_UNAVAILABLE, {
                "status": "ready" if authenticated else "login_required", "authenticated": authenticated,
                "model": MODEL, "reasoningEffort": EFFORT, "detail": detail,
            })
        elif self.path in {"/models", "/v1/models"}:
            self.send_json(HTTPStatus.OK, {"object": "list", "data": [{"id": MODEL, "object": "model", "owned_by": "openai-codex"}]})
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": {"message": "Not found"}})
            return
        size = int(self.headers.get("Content-Length", "0") or 0)
        try:
            body = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("JSON object required")
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": {"message": str(exc), "type": "invalid_request_error"}})
            return
        requested_model = str(body.get("model") or MODEL)
        response: dict[str, Any] | None = None
        duration_ms = 0
        started = time.monotonic()
        try:
            result, usage, duration_ms = run_codex_turn(body)
            response = build_chat_response(result, usage, requested_model)
            self.send_json(HTTPStatus.OK, response)
            submit_metric(self.headers, requested_model, response, HTTPStatus.OK, duration_ms)
        except Exception as exc:
            duration_ms = max(duration_ms, int((time.monotonic() - started) * 1000))
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": {"message": str(exc), "type": "codex_reference_error"}})
            submit_metric(self.headers, requested_model, response, HTTPStatus.BAD_GATEWAY, duration_ms)


def serve() -> None:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    servers = [ThreadingHTTPServer((host, PORT), Handler) for host in listener_hosts(HOST, DOCKER_HOST)]
    for server in servers[1:]:
        thread = threading.Thread(target=server.serve_forever, name=f"codex-reference-{server.server_address[0]}", daemon=True)
        thread.start()
    hosts = ",".join(str(server.server_address[0]) for server in servers)
    print(f"codex-reference listening on {hosts}:{PORT} model={MODEL} effort={EFFORT}", flush=True)
    servers[0].serve_forever()


if __name__ == "__main__":
    serve()
