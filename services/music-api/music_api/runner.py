from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from gpu45_resource import acquire_lease

from .profiles import get_profile
from .store import MusicStore, now_iso


def _atomic_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def remaining_eta(estimated_total: int, learned: bool, worker_eta: object, elapsed: float) -> int:
    if learned or worker_eta is None:
        return max(1, round(estimated_total - elapsed))
    try:
        return max(1, int(worker_eta))
    except (TypeError, ValueError):
        return max(1, round(estimated_total - elapsed))


class MusicRunner:
    def __init__(self, store: MusicStore, data_root: Path, service_root: Path):
        self.store = store
        self.data_root = data_root
        self.service_root = service_root
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="music-runner", daemon=True)
        self.processes: dict[str, subprocess.Popen[str]] = {}

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        for process in list(self.processes.values()):
            self._terminate(process)
        self.thread.join(timeout=10)

    def cancel(self, job_id: str) -> None:
        process = self.processes.get(job_id)
        if process:
            self._terminate(process)

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=20)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _loop(self) -> None:
        while not self.stop_event.wait(1):
            job = self.store.next_queued()
            if not job:
                continue
            try:
                self._run(job)
            except Exception as exc:
                self.store.update(
                    str(job["id"]),status="failed",stage="failed",progress=100,error=str(exc),
                    process_pid=None,completed_at=now_iso(),
                )

    def _worker_command(self, profile: dict[str, object], spec_path: Path) -> list[str]:
        override = os.environ.get("GPU45_MUSIC_WORKER_COMMAND")
        if override:
            return [*override.split(), "--spec", str(spec_path)]
        if profile["backend"] == "ace":
            python = os.environ.get("GPU45_ACE_PYTHON", "/opt/ace-step-venv/bin/python")
        else:
            python = os.environ.get("GPU45_LEVO_PYTHON", "/opt/levo2-venv/bin/python")
        return [python, str(self.service_root / "music_worker.py"), "--spec", str(spec_path)]

    def _run(self, job: dict[str, object]) -> None:
        job_id = str(job["id"])
        profile = get_profile(str(job["profile_id"]))
        if not profile:
            raise RuntimeError("Unknown music profile.")
        job_dir = self.data_root / "jobs" / job_id
        output_dir = job_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        progress_path = job_dir / "progress.json"
        result_path = job_dir / "result.json"
        spec_path = job_dir / "spec.json"
        spec = {
            "job": job,
            "profile": profile,
            "outputDir": str(output_dir),
            "progressPath": str(progress_path),
            "resultPath": str(result_path),
            "dataRoot": str(self.data_root),
        }
        _atomic_json(spec_path, spec)
        duration = float(job["payload"].get("duration") or profile["duration"]["default"])
        learned_total = self.store.estimate_seconds(str(job["profile_id"]), str(job["task_type"]), duration)
        estimated_total = learned_total
        if estimated_total is None:
            if profile["backend"] == "levo":
                estimated_total = 30 if str(job["task_type"]) == "separate" else 720
            elif str(job["task_type"]) in {"complete", "lego", "text2music"}:
                estimated_total = 180
            else:
                estimated_total = 75
        self.store.update(
            job_id,status="waiting",stage="waiting-for-gpu",progress=1,error=None,
            eta_seconds=estimated_total,started_at=now_iso(),
        )
        lease = acquire_lease(job_id, "music", 70, False, "ACE restarts; LeVo resumes at a verified phase boundary", timeout=1800)
        started = time.monotonic()
        peak_vram = 0
        peak_ram = 0
        peak_power: float | None = None
        peak_junction: float | None = None
        try:
            self.store.update(job_id,status="running",stage="loading",progress=2)
            log_path = job_dir / "worker.log"
            with log_path.open("a", encoding="utf-8") as log:
                process = subprocess.Popen(
                    self._worker_command(profile, spec_path),cwd=self.service_root,stdout=log,stderr=subprocess.STDOUT,
                    text=True,start_new_session=True,env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
                self.processes[job_id] = process
                self.store.update(job_id,process_pid=process.pid)
                last_progress: dict[str, object] = {}
                last_eta_write = 0.0
                while process.poll() is None:
                    current = self.store.get_job(job_id) or {}
                    if current.get("cancel_requested"):
                        self._terminate(process)
                        break
                    progress = _read_json(progress_path)
                    now = time.monotonic()
                    if progress and (progress != last_progress or now - last_eta_write >= 5):
                        if progress != last_progress:
                            last_progress = progress
                        worker_eta = progress.get("etaSeconds")
                        elapsed = now - started
                        eta = remaining_eta(estimated_total, learned_total is not None, worker_eta, elapsed)
                        self.store.update(
                            job_id,stage=str(progress.get("stage") or "generating"),
                            progress=float(progress.get("progress") or 0),
                            eta_seconds=eta,
                        )
                        last_eta_write = now
                    metrics = self._gpu_metrics()
                    peak_vram = max(peak_vram, int(metrics.get("vramBytes") or 0))
                    peak_ram = max(peak_ram, self._ram_used_bytes())
                    power = metrics.get("powerWatts")
                    if power is not None:
                        peak_power = max(peak_power or float(power), float(power))
                    junction = metrics.get("junctionC")
                    if junction is not None:
                        peak_junction = max(peak_junction or float(junction), float(junction))
                    time.sleep(1)
                return_code = process.wait(timeout=5)
            current = self.store.get_job(job_id) or {}
            metrics = {
                "generationSeconds": round(time.monotonic() - started, 2),
                "peakVramBytes": peak_vram or None,
                "peakRamBytes": peak_ram or None,
                "peakPowerWatts": peak_power,
                "peakJunctionC": peak_junction,
            }
            if current.get("cancel_requested"):
                self.store.update(job_id,status="cancelled",stage="cancelled",progress=100,metrics_json=json.dumps(metrics),process_pid=None,completed_at=now_iso())
                return
            result = _read_json(result_path)
            if return_code != 0 or not result.get("ok"):
                error = str(result.get("error") or f"Music worker exited with status {return_code}. See {log_path}.")
                self.store.update(job_id,status="failed",stage="failed",progress=100,error=error,metrics_json=json.dumps(metrics),process_pid=None,completed_at=now_iso())
                return
            assets = result.get("assets") if isinstance(result.get("assets"), dict) else {}
            metrics.update(result.get("metrics") if isinstance(result.get("metrics"), dict) else {})
            self.store.update(
                job_id,status="completed",stage="completed",progress=100,eta_seconds=0,
                assets_json=json.dumps(assets),metrics_json=json.dumps(metrics),process_pid=None,completed_at=now_iso(),
            )
        finally:
            self.processes.pop(job_id, None)
            lease.release()

    @staticmethod
    def _gpu_metrics() -> dict[str, object]:
        try:
            result = subprocess.run(
                ["/opt/rocm/bin/rocm-smi", "--showmeminfo", "vram", "--showtemp", "--showpower", "--json"],
                capture_output=True,text=True,timeout=8,check=False,
            )
            data = json.loads(result.stdout or "{}")
            gpu = next(iter(data.values()))
            return {
                "vramBytes": int(float(gpu.get("VRAM Total Used Memory (B)") or 0)),
                "powerWatts": float(gpu.get("Average Graphics Package Power (W)")) if gpu.get("Average Graphics Package Power (W)") is not None else None,
                "junctionC": float(gpu.get("Temperature (Sensor junction) (C)")) if gpu.get("Temperature (Sensor junction) (C)") is not None else None,
            }
        except (OSError, ValueError, json.JSONDecodeError, StopIteration, subprocess.SubprocessError):
            return {}

    @staticmethod
    def _ram_used_bytes() -> int:
        try:
            values: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                name, raw = line.split(":", 1)
                values[name] = int(raw.strip().split()[0]) * 1024
            return max(0, values["MemTotal"] - values["MemAvailable"])
        except (OSError, KeyError, ValueError):
            return 0


def remove_job_files(data_root: Path, job: dict[str, object]) -> None:
    job_dir = data_root / "jobs" / str(job["id"])
    if job_dir.is_dir() and job_dir.resolve().is_relative_to((data_root / "jobs").resolve()):
        shutil.rmtree(job_dir)

