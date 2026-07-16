from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import load_suite_manifests
from .harnesses import BfclAdapter, HarborAdapter, HarnessInterrupted, SweBenchAdapter, TauAdapter
from .model_catalog import discover_profiles
from .store import BenchmarkStore


class ResourcePreempted(RuntimeError):
    pass


class CampaignControlled(RuntimeError):
    pass


def request_json(url: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 30) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return response.status, json.loads(raw or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


@dataclass
class BenchmarkLease:
    lease_id: str
    client: "ResourceClient"

    def __post_init__(self) -> None:
        self.lost = threading.Event()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._heartbeat, daemon=True, name=f"benchmark-lease-{self.lease_id[:8]}")
        self.thread.start()

    def _heartbeat(self) -> None:
        while not self.stopped.wait(15):
            status, _ = self.client.post(f"/v1/leases/{self.lease_id}/heartbeat", {})
            if status != 200:
                self.lost.set()
                return

    def ensure_active(self) -> None:
        if self.lost.is_set():
            raise ResourcePreempted("Interactive work preempted the benchmark lease")

    def release(self) -> None:
        self.stopped.set()
        self.client.post(f"/v1/leases/{self.lease_id}/release", {})


class ResourceClient:
    def __init__(self) -> None:
        self.url = os.environ.get("GPU45_RESOURCE_MANAGER_URL", "http://127.0.0.1:8040").rstrip("/")
        self.token = os.environ.get("GPU45_RESOURCE_MANAGER_TOKEN", "")

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def post(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        return request_json(self.url + path, payload, self.headers, 120)

    def get(self, path: str) -> tuple[int, dict[str, Any]]:
        return request_json(self.url + path, headers=self.headers, timeout=30)

    def acquire(self, job_id: str, timeout: int = 900) -> BenchmarkLease:
        status, result = self.post("/v1/leases/acquire", {
            "jobId": job_id,
            "kind": "benchmark",
            "priority": 10,
            "preemptible": True,
            "resumePolicy": "restart-task",
        })
        if status not in {200, 202}:
            raise RuntimeError(result.get("error") or "benchmark lease rejected")
        lease_id = str(result["leaseId"])
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, state = self.get("/v1/state")
            if (state.get("owner") or {}).get("leaseId") == lease_id:
                return BenchmarkLease(lease_id, self)
            time.sleep(2)
        self.post(f"/v1/leases/{lease_id}/release", {})
        raise TimeoutError("timed out waiting for benchmark GPU lease")

    def activate(self, profile_name: str) -> None:
        status, result = self.post("/v1/provider/activate", {"profileName": profile_name})
        if status != 200:
            raise RuntimeError(result.get("error") or "profile activation failed")

    def simulator(self, action: str) -> None:
        if action not in {"start", "stop"}:
            raise ValueError("invalid simulator action")
        status, result = self.post(f"/v1/benchmark/simulator/{action}", {})
        if status != 200:
            raise RuntimeError(result.get("error") or f"simulator {action} failed")


class SmokeAdapter:
    def __init__(self, token: str, responses_url: str = "http://127.0.0.1:30001") -> None:
        self.token = token
        self.responses_url = responses_url.rstrip("/")

    @property
    def headers(self) -> dict[str, str]:
        return {"X-GPU45-Benchmark-Token": self.token, "Authorization": "Bearer gpu45-benchmark"}

    def run(self, task_name: str, model: str, lease: BenchmarkLease) -> tuple[bool, str | None]:
        if task_name == "provider-readiness":
            status, payload = request_json(self.responses_url + "/v1/models", headers=self.headers, timeout=30)
            aliases = {str(item.get("id")) for item in payload.get("data", [])}
            return status == 200 and model in aliases, None if model in aliases else f"Alias {model} was not advertised"

        if task_name in {"failed-tool-recovery", "context-continuation", "repetition-resistance"}:
            return self._run_codex_diagnostic(task_name, model, lease)

        tools = None
        prompt = "Reply with exactly the word READY."
        if task_name == "json-output":
            prompt = 'Return only this JSON object with no markdown: {"status":"ready","count":2}'
        elif task_name == "single-tool-call":
            prompt = "Call lookup_weather once for Chicago. Do not answer in text."
            tools = [{"type": "function", "name": "lookup_weather", "description": "Look up weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"], "additionalProperties": False}}]
        elif task_name == "parallel-tool-call":
            prompt = "Call lookup_weather for Chicago and Denver in parallel. Do not answer in text."
            tools = [{"type": "function", "name": "lookup_weather", "description": "Look up weather", "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"], "additionalProperties": False}}]
        elif task_name == "cancellation-vram-release":
            prompt = "Count upward forever, one number per line."
        diagnostic_tools = {
            "repository-inspection": ("read_repository_file", "Read /workspace/AGENTS.md before answering. Do not answer in text."),
            "file-edit": ("apply_patch", "Use apply_patch to change old_value to new_value in /workspace/example.txt. Do not answer in text."),
            "shell-use": ("run_shell_command", "Use the shell tool to run git status --short. Do not answer in text."),
            "web-search-tool": ("gpu45_web_search", "Search the web for the official Python documentation. Do not answer in text."),
        }
        if task_name in diagnostic_tools:
            name, prompt = diagnostic_tools[task_name]
            tools = [self._tool(name)]

        output_budget = 4096 if task_name in {"json-output", "single-tool-call", "parallel-tool-call"} else 512
        payload: dict[str, Any] = {"model": model, "input": prompt, "stream": True, "max_output_tokens": output_budget, "temperature": 0}
        if tools:
            payload["tools"] = tools
            payload["parallel_tool_calls"] = True
        events = self._stream(payload, lease, stop_early=task_name == "cancellation-vram-release")
        if task_name == "cancellation-vram-release":
            return bool(events), None if events else "No stream event arrived before cancellation"
        completed = next((event for event in events if event.get("type") == "response.completed"), None)
        if not completed:
            return False, "Stream ended without response.completed"
        response = completed.get("response") or {}
        outputs = response.get("output") or []
        if task_name == "stream-completion":
            return True, None
        if task_name == "json-output":
            text = "".join(
                str(part.get("text") or "")
                for item in outputs if item.get("type") == "message"
                for part in item.get("content", []) if part.get("type") in {"output_text", "text"}
            ).strip()
            try:
                parsed = json.loads(text)
                return parsed == {"status": "ready", "count": 2}, None if parsed == {"status": "ready", "count": 2} else f"Unexpected JSON: {text[:200]}"
            except json.JSONDecodeError:
                return False, f"Invalid JSON: {text[:200]}"
        calls = [item for item in outputs if item.get("type") == "function_call"]
        expected = 2 if task_name == "parallel-tool-call" else 1
        valid = len(calls) == expected
        if task_name in diagnostic_tools and calls:
            valid = valid and calls[0].get("name") == diagnostic_tools[task_name][0]
        return valid, None if valid else f"Expected {expected} matching tool calls, received {len(calls)}"

    @staticmethod
    def _tool(name: str) -> dict[str, Any]:
        return {
            "type": "function", "name": name, "description": f"GPU45 diagnostic tool {name}",
            "parameters": {"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"], "additionalProperties": False},
        }

    @staticmethod
    def _completed(events: list[dict[str, Any]]) -> dict[str, Any] | None:
        event = next((item for item in events if item.get("type") == "response.completed"), None)
        return (event or {}).get("response") if event else None

    @staticmethod
    def _response_text(response: dict[str, Any]) -> str:
        return "".join(
            str(part.get("text") or "")
            for item in response.get("output") or [] if item.get("type") == "message"
            for part in item.get("content") or [] if part.get("type") in {"output_text", "text"}
        ).strip()

    def _run_codex_diagnostic(self, task_name: str, model: str, lease: BenchmarkLease) -> tuple[bool, str | None]:
        if task_name == "context-continuation":
            first = self._completed(self._stream({
                "model": model, "input": "Remember the exact code GPU45-CONTEXT-7429 and reply ACK.",
                "stream": True, "max_output_tokens": 1024, "temperature": 0,
            }, lease))
            if not first or not first.get("id"):
                return False, "First context response did not complete"
            second = self._completed(self._stream({
                "model": model, "previous_response_id": first["id"], "input": "Return only the exact code I asked you to remember.",
                "stream": True, "max_output_tokens": 1024, "temperature": 0,
            }, lease))
            text = self._response_text(second or {})
            return text == "GPU45-CONTEXT-7429", None if text == "GPU45-CONTEXT-7429" else f"Context recall returned: {text[:160]}"
        if task_name == "repetition-resistance":
            response = self._completed(self._stream({
                "model": model, "input": "Write exactly 40 lines numbered ITEM 1 through ITEM 40, once each, with no other text.",
                "stream": True, "max_output_tokens": 2048, "temperature": 0,
            }, lease))
            numbers = [int(value) for value in re.findall(r"(?m)^ITEM\s+(\d+)\s*$", self._response_text(response or {}))]
            valid = numbers == list(range(1, 41))
            return valid, None if valid else f"Expected 40 unique ordered items, received {len(numbers)}"

        tools = [self._tool("unstable_tool"), self._tool("fallback_tool")]
        first = self._completed(self._stream({
            "model": model, "input": "Call unstable_tool once. If its result is an error, call fallback_tool with the same input.",
            "tools": tools, "stream": True, "max_output_tokens": 2048, "temperature": 0,
        }, lease))
        calls = [item for item in (first or {}).get("output") or [] if item.get("type") == "function_call"]
        if not first or not first.get("id") or len(calls) != 1 or calls[0].get("name") != "unstable_tool":
            return False, "Model did not make the initial unstable_tool call"
        second = self._completed(self._stream({
            "model": model, "previous_response_id": first["id"],
            "input": [{"type": "function_call_output", "call_id": calls[0].get("call_id"), "output": "ERROR: simulated tool failure"}],
            "tools": tools, "stream": True, "max_output_tokens": 2048, "temperature": 0,
        }, lease))
        recovered = [item for item in (second or {}).get("output") or [] if item.get("type") == "function_call" and item.get("name") == "fallback_tool"]
        return len(recovered) == 1, None if len(recovered) == 1 else "Model did not recover with fallback_tool"

    def _stream(self, payload: dict[str, Any], lease: BenchmarkLease, stop_early: bool = False) -> list[dict[str, Any]]:
        request = urllib.request.Request(
            self.responses_url + "/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream", **self.headers},
            method="POST",
        )
        events: list[dict[str, Any]] = []
        with urllib.request.urlopen(request, timeout=900) as response:
            data_lines: list[str] = []
            while True:
                lease.ensure_active()
                line = response.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", "replace").rstrip("\r\n")
                if decoded.startswith("data:"):
                    data_lines.append(decoded[5:].strip())
                elif not decoded and data_lines:
                    raw = "\n".join(data_lines)
                    data_lines = []
                    if raw != "[DONE]":
                        try:
                            events.append(json.loads(raw))
                        except json.JSONDecodeError:
                            pass
                    if stop_early and events:
                        break
        return events


class BenchmarkRunner:
    def __init__(self, store: BenchmarkStore, package_root: Path, appliance_db: Path, min_free_bytes: int) -> None:
        self.store = store
        self.package_root = package_root
        self.appliance_db = appliance_db
        self.min_free_bytes = min_free_bytes
        self.resources = ResourceClient()
        self.smoke = SmokeAdapter(os.environ.get("GPU45_AGENTIC_TOKEN", ""))
        self.artifact_root = Path(os.environ.get("GPU45_AGENTIC_ARTIFACT_ROOT", "/var/lib/gpu45/benchmarks/artifacts"))
        self.bfcl = BfclAdapter(Path(os.environ.get("GPU45_HARNESS_ROOT", "/opt/gpu45/benchmark-harnesses")), self.artifact_root, os.environ.get("GPU45_AGENTIC_TOKEN", ""))
        self.tau = TauAdapter(Path(os.environ.get("GPU45_HARNESS_ROOT", "/opt/gpu45/benchmark-harnesses")), self.artifact_root)
        self.swebench = SweBenchAdapter(Path(os.environ.get("GPU45_HARNESS_ROOT", "/opt/gpu45/benchmark-harnesses")), self.artifact_root)
        self.harbor = HarborAdapter(Path(os.environ.get("GPU45_HARNESS_ROOT", "/opt/gpu45/benchmark-harnesses")), self.artifact_root, os.environ.get("GPU45_AGENTIC_TOKEN", ""))
        self.stop_event = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self.run_forever, daemon=True, name="agentic-benchmark-runner").start()

    def run_forever(self) -> None:
        self._cleanup_benchmark_containers()
        while not self.stop_event.wait(3):
            try:
                self._queue_model_smokes()
                runnable = self.store.next_runnable()
                if runnable:
                    self._run(runnable)
            except Exception as exc:
                print(f"agentic-runner: scheduler error: {exc!r}", flush=True)
                time.sleep(5)

    def _queue_model_smokes(self) -> None:
        profiles = discover_profiles(self.appliance_db)
        self.store.sync_qualifications(profiles)
        suites = {suite["id"]: suite for suite in load_suite_manifests(self.package_root / "suite-manifests")}
        smoke = suites["gpu45-smoke-v1"]
        for profile in profiles:
            self.store.ensure_smoke_campaign(profile, smoke)

    def _active_profile(self) -> str | None:
        try:
            with sqlite3.connect(f"file:{self.appliance_db}?mode=ro", uri=True) as db:
                row = db.execute("SELECT name FROM LaunchProfile WHERE active=1 ORDER BY updatedAt DESC LIMIT 1").fetchone()
                return str(row[0]) if row else None
        except sqlite3.Error:
            return None

    def _run(self, runnable: dict[str, Any]) -> None:
        suite = json.loads(runnable["suite_snapshot_json"])
        if suite.get("adapter") not in {"gpu45-smoke", "bfcl", "tau", "swebench", "harbor"}:
            self.store.fail_run(runnable["id"], f"Suite adapter {suite.get('adapter')} is installed but not yet enabled")
            return
        previous = self._active_profile()
        run = self.store.begin_run(runnable["id"], previous)
        if suite.get("adapter") == "bfcl":
            tasks = self.bfcl.tasks(suite)
        elif suite.get("adapter") == "tau":
            tasks = self.tau.tasks(suite)
        elif suite.get("adapter") == "swebench":
            tasks = self.swebench.tasks(suite)
        elif suite.get("adapter") == "harbor":
            tasks = self.harbor.tasks(suite)
        else:
            tasks = [str(item) for item in suite.get("tasks", [])]
        self.store.ensure_tasks(run["id"], tasks)
        lease: BenchmarkLease | None = None
        try:
            lease = self.resources.acquire(f"agentic-{run['id']}")
            self.resources.activate(str(run["profile_name"]))
            profile = json.loads(run["profile_snapshot_json"])
            alias = str(profile.get("servedAlias") or profile["name"])
            if suite.get("adapter") == "tau":
                self.resources.simulator("start")
                self.tau.wait_ready()
            while task := self.store.next_task(run["id"]):
                control = self.store.apply_pending_control(run["campaign_id"], run["id"])
                if control:
                    raise CampaignControlled(control)
                lease.ensure_active()
                self.store.begin_task(task["id"])
                started = time.monotonic()
                try:
                    if suite.get("adapter") == "bfcl":
                        result = self.bfcl.run(
                            run["campaign_id"], run["id"], task["id"], task["external_task_id"], alias,
                            int(suite.get("timeoutSeconds") or 900), lease.ensure_active,
                            lambda: self._control_request(run["campaign_id"]),
                            int(suite.get("validationLimit") or 0),
                        )
                        self._finish_harness_result(run, task, result, "harness_failure")
                    elif suite.get("adapter") == "tau":
                        result = self.tau.run(
                            run["campaign_id"], run["id"], task["id"], task["external_task_id"], alias,
                            int(suite.get("timeoutSeconds") or 1800), lease.ensure_active,
                            lambda: self._control_request(run["campaign_id"]),
                        )
                        self._finish_harness_result(run, task, result, "model_failure")
                    elif suite.get("adapter") == "swebench":
                        result = self.swebench.run(
                            run["campaign_id"], run["id"], task["id"], task["external_task_id"], alias,
                            int(suite.get("timeoutSeconds") or 7200), lease.ensure_active,
                            lambda: self._control_request(run["campaign_id"]),
                        )
                        self._finish_harness_result(run, task, result, "model_failure")
                    elif suite.get("adapter") == "harbor":
                        result = self.harbor.run(
                            run["campaign_id"], run["id"], task["id"], task["external_task_id"], alias,
                            int(suite.get("timeoutSeconds") or 7200), lease.ensure_active,
                            lambda: self._control_request(run["campaign_id"]),
                        )
                        self._finish_harness_result(run, task, result, "model_failure")
                    else:
                        passed, message = self.smoke.run(task["external_task_id"], alias, lease)
                        self.store.complete_task(task["id"], passed, int((time.monotonic() - started) * 1000), None if passed else "model_failure", message)
                except HarnessInterrupted:
                    self._cleanup_benchmark_containers(run["campaign_id"])
                    self.store.apply_pending_control(run["campaign_id"], run["id"])
                    raise CampaignControlled("campaign control requested")
                except ResourcePreempted:
                    raise
                except Exception as exc:
                    if not self.store.retry_infrastructure_task(task["id"], "Infrastructure failed; retrying once"):
                        self.store.complete_task(task["id"], False, int((time.monotonic() - started) * 1000), "infrastructure_failure", "Smoke check could not complete", repr(exc))
        except CampaignControlled:
            pass
        except ResourcePreempted as exc:
            self._cleanup_benchmark_containers(run["campaign_id"])
            self.store.interrupt_run(run["id"], str(exc))
        except Exception as exc:
            self.store.fail_run(run["id"], str(exc))
        finally:
            if lease:
                if suite.get("adapter") == "tau":
                    try:
                        self.resources.simulator("stop")
                    except Exception as exc:
                        print(f"agentic-runner: tau simulator stop failed: {exc!r}", flush=True)
                if previous and not lease.lost.is_set():
                    try:
                        self.resources.activate(previous)
                    except Exception as exc:
                        print(f"agentic-runner: previous profile restore failed: {exc!r}", flush=True)
                lease.release()
            time.sleep(60 if lease and lease.lost.is_set() else 1)

    def _finish_harness_result(self, run: dict[str, Any], task: dict[str, Any], result: Any, default_error_class: str) -> None:
        for kind, path in result.artifacts:
            if path.is_file():
                relative = str(path.resolve().relative_to(self.artifact_root.resolve()))
                self.store.register_artifact_path(run["campaign_id"], run["id"], task["id"], kind, relative, path)
        error_class = result.error_class or (None if result.passed else default_error_class)
        if error_class == "infrastructure_failure" and self.store.retry_infrastructure_task(
            task["id"], "Infrastructure failed; retrying once"
        ):
            return
        self.store.complete_task(
            task["id"], result.passed, result.duration_ms, error_class,
            result.message, result.technical_error, result.reward,
        )

    def _cleanup_benchmark_containers(self, campaign_id: str | None = None) -> None:
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", '{{.ID}}\t{{.Names}}\t{{.Label "com.docker.compose.project.working_dir"}}'],
                capture_output=True, text=True, timeout=10, check=True,
            )
            owned: list[str] = []
            artifact_prefix = str((self.artifact_root / campaign_id).resolve()) if campaign_id else str(self.artifact_root.resolve())
            for line in result.stdout.splitlines():
                parts = line.split("\t", 2)
                if len(parts) < 2:
                    continue
                container_id, name = parts[:2]
                working_dir = parts[2] if len(parts) > 2 else ""
                if name.startswith("minisweagent-") or working_dir.startswith(artifact_prefix):
                    owned.append(container_id)
            if owned:
                subprocess.run(["docker", "rm", "-f", *owned], capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"agentic-runner: benchmark container cleanup failed: {exc!r}", flush=True)

    def _control_request(self, campaign_id: str) -> str | None:
        control = self.store.campaign_control(campaign_id)
        if not control:
            return "cancelled"
        if control["cancel_requested"]:
            return "cancelled"
        if control["pause_requested"]:
            return "paused"
        return None
