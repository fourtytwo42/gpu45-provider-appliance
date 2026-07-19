from __future__ import annotations

import statistics
import threading
import time
from pathlib import Path
from typing import Callable


def _read_number(path: Path, scale: float = 1.0) -> float | None:
    try:
        return float(path.read_text(encoding="utf-8").strip()) / scale
    except (OSError, ValueError):
        return None


def discover_gpu_card(root: Path = Path("/sys/class/drm")) -> Path | None:
    candidates: list[tuple[int, Path]] = []
    for card in root.glob("card[0-9]*"):
        try:
            if (card / "device" / "vendor").read_text(encoding="utf-8").strip().lower() != "0x1002":
                continue
        except OSError:
            continue
        total = int(_read_number(card / "device" / "mem_info_vram_total") or 0)
        candidates.append((total, card))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


class HardwareReader:
    def __init__(self, drm_root: Path = Path("/sys/class/drm"), meminfo: Path = Path("/proc/meminfo")) -> None:
        self.card = discover_gpu_card(drm_root)
        self.meminfo = meminfo
        self.hwmon = self._discover_hwmon()

    def _discover_hwmon(self) -> Path | None:
        if not self.card:
            return None
        for path in (self.card / "device" / "hwmon").glob("hwmon*"):
            try:
                if (path / "name").read_text(encoding="utf-8").strip() == "amdgpu":
                    return path
            except OSError:
                continue
        return None

    def _ram_used(self) -> int | None:
        try:
            values = {}
            for line in self.meminfo.read_text(encoding="utf-8").splitlines():
                name, value = line.split(":", 1)
                values[name] = int(value.strip().split()[0]) * 1024
            return values["MemTotal"] - values["MemAvailable"]
        except (OSError, KeyError, ValueError):
            return None

    def read(self) -> dict[str, float | int | None]:
        temperatures = []
        if self.hwmon:
            for path in self.hwmon.glob("temp*_input"):
                value = _read_number(path, 1000.0)
                if value is not None:
                    temperatures.append(value)
        return {
            "at": time.monotonic(),
            "power_w": _read_number(self.hwmon / "power1_average", 1_000_000.0) if self.hwmon else None,
            "gpu_temp_c": max(temperatures) if temperatures else None,
            "vram_bytes": int(_read_number(self.card / "device" / "mem_info_vram_used") or 0) if self.card else None,
            "ram_bytes": self._ram_used(),
        }


def measure_idle_power(reader: HardwareReader, seconds: float = 30.0, interval: float = 1.0) -> dict[str, float | int]:
    started = time.monotonic()
    values: list[float] = []
    while True:
        sample = reader.read()
        if sample["power_w"] is not None:
            values.append(float(sample["power_w"]))
        elapsed = time.monotonic() - started
        if elapsed >= seconds:
            break
        time.sleep(min(interval, max(0.0, seconds - elapsed)))
    return {
        "idle_power_w": statistics.median(values) if values else 0.0,
        "duration_seconds": max(0.0, time.monotonic() - started),
        "sample_count": len(values),
    }


class TaskResourceSampler:
    def __init__(
        self,
        reader: HardwareReader,
        idle_power_w: float = 0.0,
        interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.reader = reader
        self.idle_power_w = max(0.0, idle_power_w)
        self.interval = interval
        self.clock = clock
        self.samples: list[dict[str, float | int | None]] = []
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.started_at = 0.0

    def start(self) -> None:
        self.started_at = self.clock()
        self.samples.append(self.reader.read())
        self.thread = threading.Thread(target=self._sample, name="benchmark-resource-sampler", daemon=True)
        self.thread.start()

    def _sample(self) -> None:
        while not self.stop_event.wait(self.interval):
            self.samples.append(self.reader.read())

    def stop(self) -> dict[str, float | int | None]:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=max(2.0, self.interval * 2))
        self.samples.append(self.reader.read())
        gross_energy = 0.0
        incremental_energy = 0.0
        for previous, current in zip(self.samples, self.samples[1:]):
            duration = max(0.0, float(current["at"]) - float(previous["at"]))
            power = float(previous["power_w"] or 0.0)
            gross_energy += power * duration / 3600.0
            incremental_energy += max(0.0, power - self.idle_power_w) * duration / 3600.0

        def peak(name: str):
            values = [sample[name] for sample in self.samples if sample[name] is not None]
            return max(values) if values else None

        return {
            "wall_duration_ms": max(0, int((self.clock() - self.started_at) * 1000)),
            "idle_power_w": self.idle_power_w,
            "gross_energy_wh": gross_energy,
            "incremental_energy_wh": incremental_energy,
            "peak_power_w": peak("power_w"),
            "peak_gpu_temp_c": peak("gpu_temp_c"),
            "peak_vram_bytes": peak("vram_bytes"),
            "peak_ram_bytes": peak("ram_bytes"),
            "sample_count": len(self.samples),
        }


class WallClockSampler:
    """Measure elapsed time when the evaluated system's hardware is not local."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.started_at = 0.0

    def start(self) -> None:
        self.started_at = self.clock()

    def stop(self) -> dict[str, float | int | None]:
        return {
            "wall_duration_ms": max(0, int((self.clock() - self.started_at) * 1000)),
            "idle_power_w": 0.0,
            "gross_energy_wh": 0.0,
            "incremental_energy_wh": 0.0,
            "peak_power_w": None,
            "peak_gpu_temp_c": None,
            "peak_vram_bytes": None,
            "peak_ram_bytes": None,
            "sample_count": 0,
        }
