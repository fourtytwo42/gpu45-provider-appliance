from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.request
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
    error_class: str | None = None


def bfcl_case_passed(reward: float) -> bool:
    return reward >= 1.0


def benchmark_headers(
    token: str,
    campaign_id: str,
    run_id: str,
    task_id: str,
    attempt: int,
) -> dict[str, str]:
    return {
        "X-GPU45-Benchmark-Token": token,
        "X-GPU45-Benchmark-Campaign": campaign_id,
        "X-GPU45-Benchmark-Run": run_id,
        "X-GPU45-Benchmark-Task": task_id,
        "X-GPU45-Benchmark-Attempt": str(attempt),
    }


def harbor_agent_config(headers: dict[str, str]) -> dict[str, object]:
    """Pass benchmark correlation through Harbor's nested mini-swe-agent."""
    return {
        "model": {
            "model_kwargs": {
                "extra_headers": dict(headers),
            },
        },
    }


def stratified_sample(items: list[str], count: int) -> list[str]:
    """Select stable, evenly spaced cases so compact campaigns stay comparable."""
    if count <= 0 or count >= len(items):
        return list(items)
    if count == 1:
        return [items[0]]
    indices = [round(index * (len(items) - 1) / (count - 1)) for index in range(count)]
    return [items[index] for index in indices]


def task_attempt_root(
    artifact_root: Path,
    campaign_id: str,
    run_id: str,
    task_id: str,
    attempt: int,
) -> Path:
    if attempt < 1:
        raise ValueError("Benchmark task attempts start at 1")
    return artifact_root / campaign_id / run_id / task_id / f"attempt-{attempt}"


def openai_base_url(endpoint_url: str | None = None) -> str:
    return (endpoint_url or os.environ.get("GPU45_RESPONSES_URL", "http://127.0.0.1:30001")).rstrip("/") + "/v1"


def container_openai_base_url(endpoint_url: str | None = None) -> str:
    base = openai_base_url(endpoint_url)
    return base.replace("http://127.0.0.1:", "http://host.docker.internal:").replace("http://localhost:", "http://host.docker.internal:")


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
        self._tasks: dict[tuple[str, ...], list[str]] = {}

    def tasks(self, suite: dict[str, object]) -> list[str]:
        configured = suite.get("taskIds")
        if isinstance(configured, list):
            return [str(item) for item in configured]
        categories = tuple(str(category) for category in suite.get("categories", []))
        if categories not in self._tasks:
            tasks: list[str] = []
            for category in categories:
                command = [str(self.python), "-m", "agentic_benchmark.bfcl_driver", "--list", "--category", category]
                try:
                    result = subprocess.run(
                        command,
                        cwd=self.source,
                        env=os.environ.copy(),
                        capture_output=True,
                        text=True,
                        timeout=180,
                        check=True,
                    )
                except subprocess.CalledProcessError as exc:
                    diagnostic = (exc.stderr or exc.stdout or "no subprocess output").strip()[-4000:]
                    raise RuntimeError(f"BFCL task discovery failed for {category}: {diagnostic}") from exc
                marker = next((line[len("GPU45_TASKS="):] for line in result.stdout.splitlines() if line.startswith("GPU45_TASKS=")), None)
                if not marker:
                    raise RuntimeError(f"BFCL task discovery did not return tasks for {category}")
                tasks.extend(str(item) for item in json.loads(marker))
            self._tasks[categories] = tasks
        tasks = list(self._tasks[categories])
        per_category_limit = int(suite.get("perCategoryLimit") or 0)
        if per_category_limit:
            sampled: list[str] = []
            for category in categories:
                sampled.extend(stratified_sample([task for task in tasks if task.startswith(f"{category}::")], per_category_limit))
            tasks = sampled
        validation_limit = int(suite.get("validationLimit") or 0)
        return tasks[:validation_limit] if validation_limit else tasks

    def run(
        self,
        campaign_id: str,
        run_id: str,
        task_id: str,
        attempt: int,
        external_task_id: str,
        alias: str,
        timeout_seconds: int,
        ensure_active: Callable[[], None],
        control_state: Callable[[], str | None],
        validation_limit: int = 0,
        endpoint_url: str | None = None,
        transport: str = "responses",
    ) -> HarnessResult:
        root = task_attempt_root(self.artifact_root, campaign_id, run_id, task_id, attempt)
        results = root / "results"
        scores = root / "scores"
        log = root / "bfcl.log"
        env = os.environ.copy()
        env.update(
            OPENAI_API_KEY="gpu45-benchmark",
            OPENAI_BASE_URL=openai_base_url(endpoint_url),
            OPENAI_DEFAULT_HEADERS=json.dumps(
                benchmark_headers(self.token, campaign_id, run_id, task_id, attempt),
                separators=(",", ":"),
            ),
        )
        category, separator, case_id = external_task_id.partition("::")
        command = [
            str(self.python), "-m", "agentic_benchmark.bfcl_driver",
            "--alias", alias, "--category", category,
            "--result-root", str(results), "--score-root", str(scores),
            "--transport", transport,
        ]
        if separator:
            command.extend(["--case-id", case_id])
        elif validation_limit:
            command.extend(["--limit", str(validation_limit)])
        started = time.monotonic()
        code = run_interruptible(command, self.source, env, log, timeout_seconds, ensure_active, control_state)
        duration_ms = int((time.monotonic() - started) * 1000)
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        marker = next((line[len("GPU45_RESULT="):] for line in reversed(text.splitlines()) if line.startswith("GPU45_RESULT=")), None)
        if code or not marker:
            return HarnessResult(
                False, 0.0, duration_ms, "BFCL harness failed", text[-4000:], [("log", log)],
                error_class="infrastructure_failure",
            )
        if "Error occurred during inference" in text or "openai.NotFoundError" in text:
            return HarnessResult(
                False, 0.0, duration_ms, "BFCL inference transport failed", text[-4000:], [("log", log)],
                error_class="infrastructure_failure",
            )
        payload = json.loads(marker)
        reward = float(payload["accuracy"])
        artifacts = [("log", log)]
        score_file = Path(str(payload["scoreFile"]))
        if score_file.is_file():
            artifacts.append(("verifier", score_file))
        return HarnessResult(bfcl_case_passed(reward), reward, duration_ms, f"{payload['correct']}/{payload['total']} correct", artifacts=artifacts)


class TauAdapter:
    def __init__(self, harness_root: Path, artifact_root: Path, token: str = "") -> None:
        self.harness_root = harness_root
        self.artifact_root = artifact_root
        self.token = token
        self.source = harness_root / "sources" / "tau"
        self.python = harness_root / "venvs" / "tau" / "bin" / "python"
        self._tasks: list[str] | None = None

    def tasks(self, suite: dict[str, object]) -> list[str]:
        configured = suite.get("taskIds")
        if isinstance(configured, list):
            return [str(item) for item in configured]
        if self._tasks is None:
            result = subprocess.run(
                [str(self.python), "-m", "agentic_benchmark.tau_driver", "--list"],
                cwd=self.source,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            marker = next((line[len("GPU45_TASKS="):] for line in result.stdout.splitlines() if line.startswith("GPU45_TASKS=")), None)
            if not marker:
                raise RuntimeError("tau task discovery did not return a task list")
            self._tasks = [str(item) for item in json.loads(marker)]
        tasks = list(self._tasks)
        domains = {str(domain) for domain in suite.get("domains", [])}
        if domains:
            tasks = [task for task in tasks if task.split(":", 1)[0] in domains]
        per_domain_limit = int(suite.get("perDomainLimit") or 0)
        if per_domain_limit:
            selected: list[str] = []
            for domain in sorted(domains or {task.split(":", 1)[0] for task in tasks}):
                selected.extend(stratified_sample([task for task in tasks if task.startswith(f"{domain}:")], per_domain_limit))
            tasks = selected
        trials = max(1, int(suite.get("trials") or 1))
        if trials > 1:
            return [f"{task}:trial-{trial}" for task in tasks for trial in range(1, trials + 1)]
        return tasks

    @staticmethod
    def wait_ready(timeout: int = 300) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:30002/health", timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(2)
        raise TimeoutError("Qwythos CPU user simulator did not become ready")

    def run(
        self,
        campaign_id: str,
        run_id: str,
        task_id: str,
        attempt: int,
        external_task_id: str,
        alias: str,
        timeout_seconds: int,
        ensure_active: Callable[[], None],
        control_state: Callable[[], str | None],
        endpoint_url: str | None = None,
    ) -> HarnessResult:
        parts = external_task_id.split(":", 2)
        domain, upstream_id = parts[:2]
        root = task_attempt_root(self.artifact_root, campaign_id, run_id, task_id, attempt)
        output = root / "tau-result.json"
        log = root / "tau.log"
        command = [
            str(self.python), "-m", "agentic_benchmark.tau_driver",
            "--domain", domain, "--task-id", upstream_id,
            "--target-alias", alias, "--output", str(output),
            "--target-base-url", openai_base_url(endpoint_url),
            "--timeout", str(timeout_seconds),
        ]
        started = time.monotonic()
        env = os.environ.copy()
        env["GPU45_BENCHMARK_HEADERS"] = json.dumps(
            benchmark_headers(self.token, campaign_id, run_id, task_id, attempt),
            separators=(",", ":"),
        )
        code = run_interruptible(command, self.source, env, log, timeout_seconds + 60, ensure_active, control_state)
        duration_ms = int((time.monotonic() - started) * 1000)
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        marker = next((line[len("GPU45_RESULT="):] for line in reversed(text.splitlines()) if line.startswith("GPU45_RESULT=")), None)
        artifacts = [("log", log)]
        if output.is_file():
            artifacts.append(("trajectory", output))
        if code or not marker:
            return HarnessResult(False, 0.0, duration_ms, "tau harness failed", text[-4000:], artifacts)
        payload = json.loads(marker)
        reward = float(payload["reward"])
        return HarnessResult(reward >= 1.0, reward, duration_ms, f"reward {reward:.3f}; {payload['terminationReason']}", artifacts=artifacts)


class SweBenchAdapter:
    def __init__(self, harness_root: Path, artifact_root: Path, token: str = "") -> None:
        self.harness_root = harness_root
        self.artifact_root = artifact_root
        self.token = token
        self.mini_source = harness_root / "sources" / "miniSweAgent"
        self.mini = harness_root / "venvs" / "mini-swe-agent" / "bin" / "mini-extra"
        self.mini_python = harness_root / "venvs" / "mini-swe-agent" / "bin" / "python"
        self.mini_config = self.mini_source / "src" / "minisweagent" / "config" / "benchmarks" / "swebench.yaml"
        self.swe_source = harness_root / "sources" / "swebench"
        self.swe_python = harness_root / "venvs" / "swebench" / "bin" / "python"
        self.ids_path = harness_root / "sources" / "sweMini50" / "data" / "subsets" / "size_optimized_sample_ids.json"

    def tasks(self, suite: dict[str, object]) -> list[str]:
        configured = suite.get("taskIds")
        if isinstance(configured, list):
            return [str(item) for item in configured]
        if suite.get("taskSource") == "swe-verified-full":
            cache_root = Path(os.environ.get("GPU45_AGENTIC_CACHE_ROOT", "/models/benchmark-cache"))
            env = os.environ.copy()
            env.update(HF_HOME=str(cache_root / "huggingface"), XDG_CACHE_HOME=str(cache_root / "mini-swe-cache"))
            command = [
                str(self.mini_python), "-c",
                "import json; from datasets import load_dataset; "
                "print('GPU45_TASKS='+json.dumps([str(x['instance_id']) for x in load_dataset('princeton-nlp/SWE-bench_Verified', split='test')],separators=(',',':')))",
            ]
            result = subprocess.run(command, cwd=self.mini_source, env=env, capture_output=True, text=True, timeout=300, check=True)
            marker = next((line[len("GPU45_TASKS="):] for line in result.stdout.splitlines() if line.startswith("GPU45_TASKS=")), None)
            if not marker:
                raise RuntimeError("SWE-bench full task discovery did not return a task list")
            return [str(item) for item in json.loads(marker)]
        tasks = [str(item) for item in json.loads(self.ids_path.read_text(encoding="utf-8"))]
        return stratified_sample(tasks, int(suite.get("stratifiedTaskCount") or 0))

    def run(
        self,
        campaign_id: str,
        run_id: str,
        task_id: str,
        attempt: int,
        external_task_id: str,
        alias: str,
        timeout_seconds: int,
        ensure_active: Callable[[], None],
        control_state: Callable[[], str | None],
        endpoint_url: str | None = None,
    ) -> HarnessResult:
        root = task_attempt_root(self.artifact_root, campaign_id, run_id, task_id, attempt)
        agent_output = root / "agent"
        agent_log = root / "mini-swe-agent.log"
        verifier_log = root / "swebench-verifier.log"
        verifier_output = root / "verifier"
        generated_config = root / "gpu45-swebench.yaml"
        root.mkdir(parents=True, exist_ok=True)
        headers = benchmark_headers(self.token, campaign_id, run_id, task_id, attempt)
        yaml_headers = "".join(f"      {name}: {json.dumps(value)}\n" for name, value in headers.items())
        generated_config.write_text(
            "environment:\n"
            "  run_args:\n"
            "    - --rm\n"
            "    - --network=none\n"
            "    - --cap-drop=ALL\n"
            "    - --security-opt=no-new-privileges\n"
            "    - --pids-limit=512\n"
            "    - --memory=8g\n"
            "model:\n"
            "  model_kwargs:\n"
            f"    api_base: {openai_base_url(endpoint_url)}\n"
            f"    api_key: {json.dumps(self.token)}\n"
            "    extra_headers:\n"
            f"{yaml_headers}"
            "    temperature: 0\n"
            "    seed: 42\n"
            "    drop_params: true\n",
            encoding="utf-8",
        )
        escaped_id = external_task_id.replace("-", "\\-").replace(".", "\\.")
        agent_command = [
            str(self.mini), "swebench", "--subset", "verified", "--split", "test",
            "--filter", f"^{escaped_id}$", "--output", str(agent_output), "--workers", "1",
            "--model", f"openai/{alias}", "-c", str(self.mini_config), "-c", str(generated_config),
        ]
        started = time.monotonic()
        agent_env = os.environ.copy()
        cache_root = Path(os.environ.get("GPU45_AGENTIC_CACHE_ROOT", "/models/benchmark-cache"))
        agent_env.update(
            HOME="/var/lib/gpu45-benchmark",
            XDG_CACHE_HOME=str(cache_root / "mini-swe-cache"),
            HF_HOME=str(cache_root / "huggingface"),
            MSWEA_COST_TRACKING="ignore_errors",
        )
        agent_code = run_interruptible(
            agent_command, self.mini_source, agent_env, agent_log,
            timeout_seconds, ensure_active, control_state,
        )
        predictions = agent_output / "preds.json"
        artifacts: list[tuple[str, Path]] = [("agent-log", agent_log), ("configuration", generated_config)]
        trajectory = agent_output / external_task_id / f"{external_task_id}.traj.json"
        if trajectory.is_file():
            artifacts.append(("trajectory", trajectory))
        if predictions.is_file():
            artifacts.append(("patch", predictions))
        if agent_code or not predictions.is_file():
            text = agent_log.read_text(encoding="utf-8", errors="replace") if agent_log.exists() else ""
            return HarnessResult(False, 0.0, int((time.monotonic() - started) * 1000), "mini-SWE-agent failed", text[-4000:], artifacts, "infrastructure_failure")

        verifier_command = [
            str(self.swe_python), "-m", "agentic_benchmark.swe_eval_driver",
            "--instance-id", external_task_id, "--predictions", str(predictions),
            "--run-id", f"gpu45-{task_id}", "--report-dir", str(verifier_output),
            "--timeout", str(min(timeout_seconds, 1800)),
        ]
        verifier_code = run_interruptible(
            verifier_command, self.swe_source, agent_env, verifier_log,
            min(timeout_seconds, 2400), ensure_active, control_state,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        text = verifier_log.read_text(encoding="utf-8", errors="replace") if verifier_log.exists() else ""
        marker = next((line[len("GPU45_RESULT="):] for line in reversed(text.splitlines()) if line.startswith("GPU45_RESULT=")), None)
        artifacts.append(("verifier-log", verifier_log))
        for report in verifier_output.rglob("*.json") if verifier_output.exists() else []:
            artifacts.append(("verifier", report))
        if verifier_code or not marker:
            return HarnessResult(False, 0.0, duration_ms, "SWE-bench verifier failed", text[-4000:], artifacts, "infrastructure_failure")
        payload = json.loads(marker)
        passed = bool(payload["resolved"])
        return HarnessResult(passed, 1.0 if passed else 0.0, duration_ms, "resolved" if passed else "patch did not resolve the task", artifacts=artifacts)


class HarborAdapter:
    def __init__(self, harness_root: Path, artifact_root: Path, token: str) -> None:
        self.harness_root = harness_root
        self.artifact_root = artifact_root
        self.token = token
        self.source = harness_root / "sources" / "harbor"
        self.harbor = harness_root / "venvs" / "harbor" / "bin" / "harbor"
        cache_root = Path(os.environ.get("GPU45_AGENTIC_CACHE_ROOT", "/models/benchmark-cache"))
        preferred = cache_root / "datasets" / "terminal-bench"
        self.dataset = preferred if preferred.is_dir() else cache_root / "datasets" / "terminal-bench-2"

    def tasks(self, suite: dict[str, object]) -> list[str]:
        configured = suite.get("taskIds")
        if isinstance(configured, list):
            return [str(item) for item in configured]
        if not self.dataset.is_dir():
            raise FileNotFoundError(f"Terminal-Bench dataset is missing: {self.dataset}")
        tasks = sorted(path.name for path in self.dataset.iterdir() if (path / "task.toml").is_file())
        return stratified_sample(tasks, int(suite.get("stratifiedTaskCount") or 0))

    def run(
        self,
        campaign_id: str,
        run_id: str,
        task_id: str,
        attempt: int,
        external_task_id: str,
        alias: str,
        timeout_seconds: int,
        ensure_active: Callable[[], None],
        control_state: Callable[[], str | None],
        endpoint_url: str | None = None,
    ) -> HarnessResult:
        root = task_attempt_root(self.artifact_root, campaign_id, run_id, task_id, attempt)
        jobs = root / "jobs"
        log = root / "harbor.log"
        overlay = root / "gpu45-sandbox.yaml"
        agent_config = root / "gpu45-agent.yaml"
        root.mkdir(parents=True, exist_ok=True)
        overlay.write_text(
            "services:\n"
            "  main:\n"
            "    cap_drop: [ALL]\n"
            "    cap_add: [CHOWN, DAC_OVERRIDE, FOWNER, SETGID, SETUID]\n"
            "    security_opt: [no-new-privileges:true]\n"
            "    pids_limit: 512\n"
            "    extra_hosts: [host.docker.internal:host-gateway]\n",
            encoding="utf-8",
        )
        headers = benchmark_headers(self.token, campaign_id, run_id, task_id, attempt)
        default_headers = json.dumps(headers, separators=(",", ":"))
        agent_config.write_text(
            json.dumps(harbor_agent_config(headers), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        command = [
            str(self.harbor), "run", "--path", str(self.dataset / external_task_id),
            "--agent", "mini-swe-agent", "--model", f"openai/{alias}",
            "--n-concurrent", "1", "--n-attempts", "1", "--max-retries", "0",
            "--jobs-dir", str(jobs), "--job-name", "gpu45", "--yes",
            "--cpus", "limit", "--memory", "limit", "--override-cpus", "4",
            "--override-memory-mb", "8192", "--override-gpus", "0",
            "--extra-docker-compose", str(overlay),
            "--allow-agent-host", "host.docker.internal",
            "--agent-env", f"MSWEA_API_KEY={self.token}",
            "--agent-env", f"OPENAI_API_KEY={self.token}",
            "--agent-env", f"OPENAI_API_BASE={container_openai_base_url(endpoint_url)}",
            "--agent-env", f"OPENAI_BASE_URL={container_openai_base_url(endpoint_url)}",
            "--agent-env", f"OPENAI_DEFAULT_HEADERS={default_headers}",
            "--agent-kwarg", f"config_file={agent_config}",
            "--agent-kwarg", "max_tokens=4096",
        ]
        env = os.environ.copy()
        env.update(
            HOME="/var/lib/gpu45-benchmark",
            XDG_CACHE_HOME=str(Path(os.environ.get("GPU45_AGENTIC_CACHE_ROOT", "/models/benchmark-cache")) / "harbor-cache"),
            HF_HOME=str(Path(os.environ.get("GPU45_AGENTIC_CACHE_ROOT", "/models/benchmark-cache")) / "huggingface"),
            DO_NOT_TRACK="1",
        )
        started = time.monotonic()
        code = run_interruptible(command, self.source, env, log, timeout_seconds, ensure_active, control_state)
        duration_ms = int((time.monotonic() - started) * 1000)
        result_path = jobs / "gpu45" / "result.json"
        artifacts: list[tuple[str, Path]] = [
            ("log", log),
            ("configuration", overlay),
            ("configuration", agent_config),
        ]
        if result_path.is_file():
            artifacts.append(("verifier", result_path))
        for trajectory in jobs.rglob("trajectory.json") if jobs.exists() else []:
            artifacts.append(("trajectory", trajectory))
        text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        if code or not result_path.is_file():
            return HarnessResult(False, 0.0, duration_ms, "Harbor task failed", text[-4000:], artifacts, "infrastructure_failure")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        trials = payload.get("trial_results") or []
        if not trials:
            trial_paths = sorted(path for path in (jobs / "gpu45").glob("*/result.json") if path != result_path)
            trials = [json.loads(path.read_text(encoding="utf-8")) for path in trial_paths]
            artifacts.extend(("verifier", path) for path in trial_paths)
        if not trials:
            return HarnessResult(False, 0.0, duration_ms, "Harbor produced no trial result", text[-4000:], artifacts, "infrastructure_failure")
        trial = trials[0]
        exception = trial.get("exception_info")
        rewards = ((trial.get("verifier_result") or {}).get("rewards") or {})
        numeric = [float(value) for value in rewards.values() if isinstance(value, (int, float))]
        reward = float(rewards.get("reward", max(numeric, default=0.0)))
        if exception:
            technical = str(exception.get("exception_message") or exception)
            return HarnessResult(False, 0.0, duration_ms, "Harbor infrastructure failed", technical, artifacts, "infrastructure_failure")
        return HarnessResult(reward > 0.0, reward, duration_ms, f"verifier reward {reward:.3f}", artifacts=artifacts)
