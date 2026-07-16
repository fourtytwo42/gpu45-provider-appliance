from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


class HarnessInterrupted(RuntimeError):
    pass


@dataclass
class HarnessResult:
    passed: bool
    reward: float
    duration_ms: int
    message: str | None = None
    technical_error: str | None = None
    artifacts: list[tuple[str, Path]] = field(default_factory=list)


def run_interruptible(
    command: list[str],
    cwd: Path,
    env: dict[str, str],
    stdout_path: Path,
    timeout_seconds: int,
    ensure_active: Callable[[], None],
    control_state: Callable[[], str | None],
) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with stdout_path.open("wb") as output:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            while process.poll() is None:
                ensure_active()
                state = control_state()
                if state:
                    raise HarnessInterrupted(state)
                if time.monotonic() - started > timeout_seconds:
                    raise TimeoutError(f"Harness exceeded {timeout_seconds} seconds")
                time.sleep(1)
            return int(process.returncode or 0)
        except BaseException:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.terminate()
                process.wait(timeout=10)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    if hasattr(os, "killpg"):
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                process.wait(timeout=10)
            raise


class BfclAdapter:
    def __init__(self, harness_root: Path, artifact_root: Path, token: str) -> None:
        self.harness_root = harness_root
        self.artifact_root = artifact_root
        self.token = token
        self.source = harness_root / "sources" / "bfcl" / "berkeley-function-call-leaderboard"
        self.python = harness_root / "venvs" / "bfcl" / "bin" / "python"

    def tasks(self, suite: dict[str, object]) -> list[str]:
        return [str(category) for category in suite.get("categories", [])]

    def run(
        self,
        campaign_id: str,
        run_id: str,
        task_id: str,
        category: str,
        alias: str,
        timeout_seconds: int,
        ensure_active: Callable[[], None],
        control_state: Callable[[], str | None],
        validation_limit: int = 0,
    ) -> HarnessResult:
        root = self.artifact_root / campaign_id / run_id / task_id
        results = root / "results"
        scores = root / "scores"
        log = root / "bfcl.log"
        env = os.environ.copy()
        env.update(
            OPENAI_API_KEY="gpu45-benchmark",
            OPENAI_BASE_URL=os.environ.get("GPU45_RESPONSES_URL", "http://127.0.0.1:30001").rstrip("/") + "/v1",
            OPENAI_DEFAULT_HEADERS=json.dumps({"X-GPU45-Benchmark-Token": self.token}),
        )
        command = [
            str(self.python), "-m", "agentic_benchmark.bfcl_driver",
            "--alias", alias, "--category", category,
            "--result-root", str(results), "--score-root", str(scores),
        ]
        if validation_limit:
            command.extend(["--limit", str(validation_limit)])
        started = time.monotonic()
        code = run_interruptible(command, self.source, env, log, timeout_seconds, ensure_active, control_state)
        duration_ms = int((time.monotonic() - started) * 1000)
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        marker = next((line[len("GPU45_RESULT="):] for line in reversed(text.splitlines()) if line.startswith("GPU45_RESULT=")), None)
        if code or not marker:
            return HarnessResult(False, 0.0, duration_ms, "BFCL harness failed", text[-4000:], [("log", log)])
        payload = json.loads(marker)
        reward = float(payload["accuracy"])
        artifacts = [("log", log)]
        score_file = Path(str(payload["scoreFile"]))
        if score_file.is_file():
            artifacts.append(("verifier", score_file))
        return HarnessResult(True, reward, duration_ms, f"{payload['correct']}/{payload['total']} correct", artifacts=artifacts)
