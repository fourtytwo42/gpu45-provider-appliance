from __future__ import annotations

import json
import csv
import io
import os
import shutil
import sqlite3
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .domain import load_suite_manifests
from .model_catalog import discover_profiles
from .runner import BenchmarkRunner
from .store import BenchmarkStore

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(os.environ.get("GPU45_AGENTIC_DB", "/var/lib/gpu45/benchmarks/agentic.db"))
APPLIANCE_DATABASE_PATH = Path(os.environ.get("GPU45_APPLIANCE_DB", "/var/lib/gpu45/appliance.db"))
ARTIFACT_ROOT = Path(os.environ.get("GPU45_AGENTIC_ARTIFACT_ROOT", "/var/lib/gpu45/benchmarks/artifacts"))
CACHE_ROOT = Path(os.environ.get("GPU45_AGENTIC_CACHE_ROOT", "/models/benchmark-cache"))
TOKEN = os.environ.get("GPU45_AGENTIC_TOKEN", "")
HOST = os.environ.get("GPU45_AGENTIC_HOST", "127.0.0.1")
PORT = int(os.environ.get("GPU45_AGENTIC_PORT", "8055"))
MIN_FREE_BYTES = int(os.environ.get("GPU45_AGENTIC_MIN_FREE_GB", "100")) * 1024**3

STORE = BenchmarkStore(DATABASE_PATH, PACKAGE_ROOT / "schema.sql")


def docker_status() -> dict[str, object]:
    command = shutil.which("docker")
    if not command:
        return {"installed": False, "ready": False, "version": None}
    try:
        result = subprocess.run([command, "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=5, check=False)
        version = result.stdout.strip() or None
        return {"installed": True, "ready": result.returncode == 0, "version": version}
    except (OSError, subprocess.SubprocessError):
        return {"installed": True, "ready": False, "version": None}


def storage_status() -> dict[str, object]:
    probe = CACHE_ROOT if CACHE_ROOT.exists() else CACHE_ROOT.parent
    usage = shutil.disk_usage(probe)
    return {"freeBytes": usage.free, "totalBytes": usage.total, "minimumFreeBytes": MIN_FREE_BYTES, "ready": usage.free >= MIN_FREE_BYTES}


def service_status() -> dict[str, object]:
    suites = load_suite_manifests(PACKAGE_ROOT / "suite-manifests")
    profiles = discover_profiles(APPLIANCE_DATABASE_PATH)
    pending = STORE.sync_qualifications(profiles)
    return {
        "status": "ready",
        "database": str(DATABASE_PATH),
        "artifactRoot": str(ARTIFACT_ROOT),
        "models": len(profiles),
        "pendingQualifications": len(STORE.pending_qualification_names()),
        "suites": len(suites),
        "docker": docker_status(),
        "storage": storage_status(),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "GPU45AgenticBenchmark/1.0"

    def log_message(self, message: str, *args: object) -> None:
        print(f"agentic-api: {message % args}", flush=True)

    def _authorized(self) -> bool:
        if not TOKEN:
            return False
        return self.headers.get("Authorization", "") == f"Bearer {TOKEN}"

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _download(self, content_type: str, filename: str, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, object]:
        size = int(self.headers.get("Content-Length", "0"))
        if size > 1_000_000:
            raise ValueError("Request body is too large")
        payload = json.loads(self.rfile.read(size) or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        return payload

    def _segments(self) -> list[str]:
        return [segment for segment in urlparse(self.path).path.split("/") if segment]

    def do_GET(self) -> None:  # noqa: N802
        segments = self._segments()
        if segments == ["health"]:
            self._json(HTTPStatus.OK, service_status())
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
            return
        try:
            if segments == ["v1", "models"]:
                profiles = discover_profiles(APPLIANCE_DATABASE_PATH)
                STORE.sync_qualifications(profiles)
                qualifications = {row["profile_name"]: row for row in STORE.list_qualifications()}
                self._json(HTTPStatus.OK, {"models": [{**profile, "qualification": qualifications.get(profile["name"])} for profile in profiles]})
            elif segments == ["v1", "suites"]:
                self._json(HTTPStatus.OK, {"suites": load_suite_manifests(PACKAGE_ROOT / "suite-manifests")})
            elif segments == ["v1", "campaigns"]:
                self._json(HTTPStatus.OK, {"campaigns": STORE.list_campaigns()})
            elif len(segments) == 3 and segments[:2] == ["v1", "campaigns"]:
                detail = STORE.campaign_detail(segments[2])
                self._json(HTTPStatus.OK if detail else HTTPStatus.NOT_FOUND, detail or {"error": "Campaign not found"})
            elif len(segments) == 4 and segments[:2] == ["v1", "campaigns"] and segments[3] == "tasks":
                query = parse_qs(urlparse(self.path).query)
                self._json(HTTPStatus.OK, STORE.list_tasks(segments[2], int(query.get("cursor", ["0"])[0]), int(query.get("limit", ["50"])[0])))
            elif len(segments) == 4 and segments[:2] == ["v1", "campaigns"] and segments[3] == "export":
                export = STORE.export_rows(segments[2])
                if not export:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Campaign not found"})
                    return
                query = parse_qs(urlparse(self.path).query)
                export_format = query.get("format", ["json"])[0].lower()
                if export_format == "csv":
                    buffer = io.StringIO()
                    fields = ["profile_name", "suite_id", "external_task_id", "status", "passed", "reward", "duration_ms", "error_class", "user_message"]
                    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
                    writer.writeheader()
                    writer.writerows(export["tasks"])
                    self._download("text/csv; charset=utf-8", f"agentic-{segments[2]}.csv", buffer.getvalue().encode())
                elif export_format == "markdown":
                    campaign = export["campaign"]
                    lines = [f"# {campaign['name']}", "", f"Status: {campaign['status']}", "", "## Results", "", "| Model | Suite | Task | Status | Reward |", "|---|---|---|---|---:|"]
                    lines.extend(f"| {row['profile_name']} | {row['suite_id']} | {row['external_task_id']} | {row['status']} | {row.get('reward') if row.get('reward') is not None else ''} |" for row in export["tasks"])
                    self._download("text/markdown; charset=utf-8", f"agentic-{segments[2]}.md", ("\n".join(lines) + "\n").encode())
                else:
                    self._download("application/json", f"agentic-{segments[2]}.json", json.dumps(export, indent=2, default=str).encode())
            elif len(segments) == 5 and segments[:2] == ["v1", "campaigns"] and segments[3] == "artifacts":
                artifact = STORE.artifact(segments[2], segments[4])
                if not artifact:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Artifact not found"})
                    return
                root = ARTIFACT_ROOT.resolve()
                target = (root / artifact["relative_path"]).resolve()
                if not target.is_relative_to(root) or not target.is_file():
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Artifact file is missing"})
                    return
                self._download("application/octet-stream", target.name, target.read_bytes())
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        except (ValueError, OSError, sqlite3.Error) as exc:  # type: ignore[name-defined]
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
            return
        segments = self._segments()
        try:
            body = self._body()
            if segments == ["v1", "campaigns"]:
                profiles = discover_profiles(APPLIANCE_DATABASE_PATH)
                by_name = {profile["name"]: profile for profile in profiles}
                manifests = load_suite_manifests(PACKAGE_ROOT / "suite-manifests")
                by_suite = {suite["id"]: suite for suite in manifests}
                requested_profiles = [by_name[name] for name in body.get("profileNames", []) if name in by_name]  # type: ignore[union-attr]
                requested_suites = [by_suite[suite_id] for suite_id in body.get("suiteIds", []) if suite_id in by_suite]  # type: ignore[union-attr]
                campaign_id = STORE.create_campaign(str(body.get("name") or "Agentic benchmark campaign"), str(body.get("preset") or "custom"), requested_profiles, requested_suites)
                self._json(HTTPStatus.ACCEPTED, {"id": campaign_id})
            elif len(segments) == 4 and segments[:2] == ["v1", "models"] and segments[3] == "smoke":
                found = STORE.retry_qualification(segments[2])
                self._json(HTTPStatus.ACCEPTED if found else HTTPStatus.NOT_FOUND, {"ok": found})
            elif len(segments) == 4 and segments[:2] == ["v1", "campaigns"] and segments[3] == "action":
                found = STORE.set_campaign_action(segments[2], str(body.get("action") or ""))
                self._json(HTTPStatus.OK if found else HTTPStatus.NOT_FOUND, {"ok": found})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
        except (ValueError, KeyError, OSError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


def serve() -> None:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    STORE.initialize()
    BenchmarkRunner(STORE, PACKAGE_ROOT, APPLIANCE_DATABASE_PATH, MIN_FREE_BYTES).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"GPU45 agentic benchmark coordinator listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()
