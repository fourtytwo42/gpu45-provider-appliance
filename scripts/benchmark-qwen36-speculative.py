#!/usr/bin/env python3
"""Run repeatable Qwen3.6 speculative decoding probes against llama-server."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def build_rewrite_prompt() -> str:
    source = "\n\n".join(
        f"def transform_{index}(value: int) -> int:\n"
        f"    \"\"\"Transform value for pipeline stage {index}.\"\"\"\n"
        f"    adjusted = value + {index}\n"
        f"    return adjusted * {index + 1}"
        for index in range(80)
    )
    return (
        "Return the complete module below with every function preserved. Add `category: str = \"gpu\"` "
        "as a keyword-only argument to every function and mention category in each docstring. "
        "Do not omit unchanged functions. Return code only.\n\n" + source
    )


def build_long_context_prompt() -> str:
    records = "\n".join(
        f"record_{index:04d} = id:{index:04d}; value:{(index * 7919) % 100000:05d}; "
        f"group:{index % 37:02d}; marker:M{(index * 104729) % 1000000:06d}"
        for index in range(350)
    )
    return (
        "Read every record. Reply with only the complete line for record_0349.\n\n"
        + records
    )


PROMPTS = {
    "coding": (
        "Write a complete Python 3 module implementing a thread-safe, persistent LRU cache. "
        "Include type hints, SQLite persistence, TTL expiration, structured logging, docstrings, "
        "and unittest tests. Return code only and continue until the implementation and tests are complete."
    ),
    "creative": (
        "Write a vivid science-fiction short story about an engineer repairing a weather satellite "
        "during a solar storm. Maintain character continuity, concrete physical detail, and a clear ending."
    ),
    "reasoning": (
        "Design a reliable job scheduler for one GPU shared by an LLM, TTS, image, and video workers. "
        "Analyze priorities, leases, cancellation, crash recovery, starvation, persistence, and testing in detail."
    ),
    "rewrite": build_rewrite_prompt(),
    "long-context": build_long_context_prompt(),
    "cache-incremental": build_long_context_prompt(),
}


def post_json(url: str, payload: dict, timeout: int) -> tuple[dict, float]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    return body, time.monotonic() - started


def first_choice(body: dict) -> dict:
    choices = body.get("choices") or []
    return choices[0] if choices else {}


def run_generation(args: argparse.Namespace, run: int) -> dict:
    prompt = PROMPTS[args.kind]
    if args.kind == "cache-incremental" and run > 0:
        prompt += (
            "\n\nFollow-up: reply with only the complete line for record_0348 instead. "
            "Do not repeat the previous answer."
        )
    body, elapsed = post_json(
        f"{args.url.rstrip('/')}/v1/chat/completions",
        {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "top_p": 1,
            "top_k": 1,
            "seed": 42 + run,
            "max_tokens": args.max_tokens,
            "stream": False,
        },
        args.timeout,
    )
    choice = first_choice(body)
    message = choice.get("message") or {}
    usage = body.get("usage") or {}
    timings = body.get("timings") or {}
    completion_tokens = usage.get("completion_tokens") or timings.get("predicted_n") or 0
    return {
        "label": args.label,
        "kind": args.kind,
        "run": run + 1,
        "requestedOutputTokens": args.max_tokens,
        "promptTokens": usage.get("prompt_tokens") or timings.get("prompt_n"),
        "completionTokens": completion_tokens,
        "promptTokensPerSecond": timings.get("prompt_per_second"),
        "decodeTokensPerSecond": timings.get("predicted_per_second"),
        "wallSeconds": round(elapsed, 3),
        "finishReason": choice.get("finish_reason"),
        "contentCharacters": len(message.get("content") or ""),
        "hasToolCalls": bool(message.get("tool_calls")),
    }


def run_tool(args: argparse.Namespace, run: int) -> dict:
    body, elapsed = post_json(
        f"{args.url.rstrip('/')}/v1/chat/completions",
        {
            "model": args.model,
            "messages": [{"role": "user", "content": "Look up the weather in Chicago."}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get weather for a city.",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                            "additionalProperties": False,
                        },
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "get_weather"}},
            "temperature": 0,
            "seed": 42,
            "max_tokens": args.max_tokens,
            "stream": False,
        },
        args.timeout,
    )
    choice = first_choice(body)
    calls = ((choice.get("message") or {}).get("tool_calls") or [])
    function = (calls[0].get("function") or {}) if calls else {}
    raw_arguments = function.get("arguments") or ""
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError:
        arguments = None
    return {
        "label": args.label,
        "kind": "tool",
        "run": run + 1,
        "wallSeconds": round(elapsed, 3),
        "finishReason": choice.get("finish_reason"),
        "functionName": function.get("name"),
        "arguments": arguments,
        "valid": function.get("name") == "get_weather" and arguments == {"city": "Chicago"},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18001")
    parser.add_argument("--model", default="Qwen3.6-27B-MTP-Eval")
    parser.add_argument("--label", required=True)
    parser.add_argument("--kind", choices=(*PROMPTS, "tool"), required=True)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    for run in range(args.runs):
        result = run_tool(args, run) if args.kind == "tool" else run_generation(args, run)
        print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
