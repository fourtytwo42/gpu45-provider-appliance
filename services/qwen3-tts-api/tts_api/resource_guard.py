"""Host resource guard for sharing VRAM between llama.cpp and Qwen3-TTS."""

from __future__ import annotations

import glob
import os
import subprocess
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator
from gpu45_resource import acquire_lease

_LEASE_LOCAL = threading.local()


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

    depth = int(getattr(_LEASE_LOCAL, "depth", 0))
    if depth > 0:
        _LEASE_LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _LEASE_LOCAL.depth -= 1
        return

    background = reason in {"audiobook", "presentation"} or "train" in reason
    lease = acquire_lease(f"tts-{os.getpid()}-{reason}", "tts", 50 if background else 70, background, "chunk-boundary" if background else "restart")
    _LEASE_LOCAL.depth = 1
    try:
        yield
    finally:
        _LEASE_LOCAL.depth = 0
        lease.release()
