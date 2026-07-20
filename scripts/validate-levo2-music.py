#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/opt/gpu45/current/services/common")

from gpu45_resource import acquire_lease  # noqa: E402


MODEL_ROOT = Path(os.environ.get("LEVO_MODEL_ROOT", "/models/music/levo2"))
SERVICE_ROOT = Path(os.environ.get("GPU45_MUSIC_SERVICE_ROOT", "/opt/gpu45-music-api"))
PYTHON = os.environ.get("GPU45_LEVO_PYTHON", "/opt/levo2-venv/bin/python")
VALIDATION_ROOT = Path(os.environ.get("GPU45_LEVO_VALIDATION_ROOT", "/models/music/validation/levo2"))
VALIDATION_PATH = MODEL_ROOT / "validation.json"
TIMEOUT_SECONDS = int(os.environ.get("GPU45_LEVO_VALIDATION_TIMEOUT", "720"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def stop_process(process: subprocess.Popen[str]) -> None:
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


def main() -> int:
    VALIDATION_ROOT.mkdir(parents=True, exist_ok=True)
    output_dir = VALIDATION_ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = VALIDATION_ROOT / "progress.json"
    result_path = VALIDATION_ROOT / "result.json"
    spec_path = VALIDATION_ROOT / "spec.json"
    for path in (progress_path, result_path):
        path.unlink(missing_ok=True)

    job_id = f"levo-validation-{int(time.time())}"
    lyrics = (
        "[intro-short] ; [verse] Wires in the moonlight carry every sound, "
        "steady as a heartbeat moving underground ; [chorus] Raise the signal, "
        "let the rhythm come alive, every voice together as the new day arrives ; "
        "[verse] Circuits turn to music and the music turns to flame, every careful "
        "motion calls the future by its name ; [chorus] Raise the signal, let the "
        "rhythm come alive, every voice together as the new day arrives ; [outro-short]"
    )
    spec = {
        "job": {
            "id": job_id,
            "profile_id": "levo2-large-amd",
            "mode": "create",
            "task_type": "text2music",
            "payload": {
                "caption": "Polished uplifting synth-rock song with expressive lead vocals, live drums, analog bass, wide guitars, and an anthemic chorus",
                "lyrics": lyrics,
                "duration": 60,
                "language": "en",
                "seed": 42,
            },
        },
        "profile": {
            "id": "levo2-large-amd",
            "backend": "levo",
            "model": "SongGeneration-v2-large",
            "lmModel": None,
        },
        "outputDir": str(output_dir),
        "progressPath": str(progress_path),
        "resultPath": str(result_path),
        "dataRoot": "/models/music",
    }
    write_json(spec_path, spec)
    write_json(VALIDATION_PATH, {"status": "testing", "startedAt": now_iso(), "reason": "LeVo AMD hardware validation is running."})

    lease = None
    process: subprocess.Popen[str] | None = None
    started = time.monotonic()
    log_path = VALIDATION_ROOT / "worker.log"
    try:
        lease = acquire_lease(job_id, "music", 70, False, "LeVo validation restarts from its last verified phase", timeout=1800)
        environment = {**os.environ, "PYTHONUNBUFFERED": "1"}
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [PYTHON, str(SERVICE_ROOT / "music_worker.py"), "--spec", str(spec_path)],
                cwd=SERVICE_ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
                env=environment,
            )
            last_report = 0.0
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > TIMEOUT_SECONDS:
                    stop_process(process)
                    raise TimeoutError(f"LeVo exceeded the {TIMEOUT_SECONDS}-second hardware validation limit.")
                if elapsed - last_report >= 15:
                    state = read_json(progress_path)
                    print(json.dumps({"elapsedSeconds": round(elapsed, 1), **state}), flush=True)
                    last_report = elapsed
                time.sleep(1)
            return_code = process.wait(timeout=5)

        elapsed = round(time.monotonic() - started, 2)
        result = read_json(result_path)
        if return_code != 0 or not result.get("ok"):
            raise RuntimeError(str(result.get("error") or f"LeVo worker exited with status {return_code}."))
        assets = result.get("assets") if isinstance(result.get("assets"), dict) else {}
        metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
        output = Path(str(assets.get("master") or ""))
        duration = float(metrics.get("durationSeconds") or 0)
        if not output.is_file():
            raise RuntimeError("LeVo validation completed without a readable master output.")
        if elapsed > 600:
            raise RuntimeError(f"LeVo required {elapsed:.1f} seconds, exceeding the 10-minute retention gate.")
        if duration < 45 or duration > 100:
            raise RuntimeError(f"LeVo returned {duration:.1f} seconds for the 60-second validation target.")
        validation = {
            "status": "passed",
            "startedAt": datetime.fromtimestamp(time.time() - elapsed, timezone.utc).isoformat(),
            "completedAt": now_iso(),
            "sourceRevision": "cdeff00366d7a07abbcfe71b0156277eeca2855d",
            "runtime": "PyTorch 2.9.1 ROCm 6.4 SDPA",
            "generationSeconds": elapsed,
            "durationSeconds": duration,
            "realTimeFactor": round(elapsed / duration, 4),
            "output": str(output),
            "metrics": metrics,
        }
        write_json(VALIDATION_PATH, validation)
        print(json.dumps(validation, indent=2), flush=True)
        return 0
    except Exception as exc:
        failure = {
            "status": "failed",
            "completedAt": now_iso(),
            "reason": str(exc),
            "log": str(log_path),
            "progress": read_json(progress_path),
        }
        write_json(VALIDATION_PATH, failure)
        print(json.dumps(failure, indent=2), file=sys.stderr, flush=True)
        return 1
    finally:
        if process is not None:
            stop_process(process)
        if lease is not None:
            lease.release()


if __name__ == "__main__":
    raise SystemExit(main())
