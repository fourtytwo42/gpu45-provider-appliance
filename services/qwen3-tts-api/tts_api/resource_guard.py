"""Host resource guard for sharing VRAM between llama.cpp and Qwen3-TTS."""

from __future__ import annotations

import glob
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


def _truthy(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class VramState:
    total_mb: int
    used_mb: int
    free_mb: int
    source: str


def read_vram_state() -> VramState | None:
    for device_path in glob.glob(os.environ.get("QWEN_TTS_GPU_CARD_GLOB", "/sys/class/drm/card*/device")):
        total_path = os.path.join(device_path, "mem_info_vram_total")
        used_path = os.path.join(device_path, "mem_info_vram_used")
        if not os.path.exists(total_path) or not os.path.exists(used_path):
            continue
        try:
            total = int(open(total_path, "r", encoding="utf-8").read().strip())
            used = int(open(used_path, "r", encoding="utf-8").read().strip())
        except (OSError, ValueError):
            continue
        total_mb = total // (1024 * 1024)
        used_mb = used // (1024 * 1024)
        return VramState(total_mb=total_mb, used_mb=used_mb, free_mb=max(total_mb - used_mb, 0), source=device_path)
    return None


def _systemctl(action: str, service: str) -> None:
    command = ["/usr/bin/sudo", "-n", "/usr/bin/systemctl", action, service]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        fallback = ["/usr/bin/systemctl", action, service]
        result = subprocess.run(fallback, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Unable to {action} {service}: {message}")


def _service_is_active(service: str) -> bool:
    result = subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", service], check=False)
    return result.returncode == 0


def _uses_gpu(device: str | None) -> bool:
    value = (device or os.environ.get("QWEN_TTS_DEVICE", "cuda:0") or "").strip().lower()
    return bool(value) and value != "cpu"


def _wait_for_free_vram(min_free_mb: int, timeout_s: int = 45) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        state = read_vram_state()
        if state is None or state.free_mb >= min_free_mb:
            return
        time.sleep(1)


@contextmanager
def tts_vram_guard(reason: str, device: str | None = None, exclusive: bool | None = None) -> Iterator[None]:
    if not _truthy(os.environ.get("QWEN_TTS_VRAM_GUARD"), True):
        yield
        return
    if not _uses_gpu(device):
        yield
        return

    min_free_mb = int(os.environ.get("QWEN_TTS_MIN_FREE_VRAM_MB", "8192"))
    service = os.environ.get("QWEN_TTS_LLM_SERVICE", "llama-openai.service")
    restart_after = _truthy(os.environ.get("QWEN_TTS_RESTART_LLM_AFTER"), False)
    exclusive_gpu = _truthy(os.environ.get("QWEN_TTS_EXCLUSIVE_GPU"), True) if exclusive is None else exclusive
    stopped = False

    state = read_vram_state()
    should_stop = exclusive_gpu and _service_is_active(service)
    should_stop = should_stop or (state is not None and state.free_mb < min_free_mb)
    if should_stop:
        detail = "exclusive GPU access requested"
        if state is not None and state.free_mb < min_free_mb:
            detail = f"free VRAM {state.free_mb} MiB below {min_free_mb} MiB"
        print(
            f"[vram-guard] {reason}: {detail}; stopping {service}",
            flush=True,
        )
        _systemctl("stop", service)
        stopped = True
        _wait_for_free_vram(min_free_mb)

    try:
        yield
    finally:
        if stopped and restart_after:
            print(f"[vram-guard] restarting {service} after {reason}", flush=True)
            _systemctl("start", service)
