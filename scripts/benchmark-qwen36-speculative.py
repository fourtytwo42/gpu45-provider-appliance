#!/usr/bin/env python3
"""Run repeatable Qwen3.6 speculative decoding probes against llama-server."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


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


class HardwareSampler:
    """Collect lightweight amdgpu sysfs peaks while a benchmark request runs."""

    def __init__(self, device: Path, interval: float = 0.25) -> None:
        self.device = device
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.samples: list[dict[str, float]] = []

    @staticmethod
    def _read_number(path: Path, scale: float = 1.0) -> float | None:
        try:
            return float(path.read_text(encoding="utf-8").strip()) / scale
        except (OSError, ValueError):
            return None

    def _sample(self) -> None:
        hwmon = next(iter(sorted(self.device.glob("hwmon/hwmon*"))), None)
        sample: dict[str, float] = {}
        busy = self._read_number(self.device / "gpu_busy_percent")
        vram = self._read_number(self.device / "mem_info_vram_used")
        if busy is not None:
            sample["gpuBusyPercent"] = busy
        if vram is not None:
            sample["vramUsedBytes"] = vram
        if hwmon:
            temperatures = [
                value
                for path in hwmon.glob("temp*_input")
                if (value := self._read_number(path, 1000.0)) is not None
            ]
            powers = [
                value
                for path in hwmon.glob("power*_average")
                if (value := self._read_number(path, 1_000_000.0)) is not None
            ]
            if temperatures:
                sample["temperatureC"] = max(temperatures)
            if powers:
                sample["powerW"] = max(powers)
        if sample:
            self.samples.append(sample)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            self._sample()

    def __enter__(self) -> "HardwareSampler":
        if self.device.exists():
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
        self._sample()

    def summary(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for key in {key for sample in self.samples for key in sample}:
            values = [sample[key] for sample in self.samples if key in sample]
            if values:
                result[f"peak{key[0].upper()}{key[1:]}"] = round(max(values), 3)
        return result


def output_integrity(content: str) -> dict[str, object]:
    normalized_lines = [re.sub(r"\s+", " ", line).strip() for line in content.splitlines()]
    meaningful = [line for line in normalized_lines if len(line) >= 24]
    duplicates = len(meaningful) - len(set(meaningful))
    return {
        "contentSha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "repeatedLineCount": duplicates,
        "repeatedLineRatio": round(duplicates / len(meaningful), 4) if meaningful else 0.0,
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
    with HardwareSampler(Path(args.gpu_device)) as sampler:
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
    content = message.get("content") or ""
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
        "contentCharacters": len(content),
        "hasToolCalls": bool(message.get("tool_calls")),
        "metadata": args.metadata,
        **output_integrity(content),
        **sampler.summary(),
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
    parser.add_argument("--gpu-device", default="/sys/class/drm/card1/device")
    parser.add_argument("--metadata-json", default="{}")
    args = parser.parse_args()
    try:
        args.metadata = json.loads(args.metadata_json)
    except json.JSONDecodeError as exc:
        parser.error(f"invalid --metadata-json: {exc}")

    for run in range(args.runs):
        result = run_tool(args, run) if args.kind == "tool" else run_generation(args, run)
        print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
