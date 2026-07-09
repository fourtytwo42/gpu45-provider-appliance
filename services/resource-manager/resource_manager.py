#!/usr/bin/env python3
"""Durable, loopback-only GPU lease manager for the GPU45 appliance."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import urllib.request

DB_PATH = Path(os.environ.get("GPU45_RESOURCE_DB", "/var/lib/gpu45/resource-manager.db"))
TOKEN = os.environ.get("GPU45_RESOURCE_MANAGER_TOKEN", "")
HOST = os.environ.get("GPU45_RESOURCE_MANAGER_HOST", "127.0.0.1")
PORT = int(os.environ.get("GPU45_RESOURCE_MANAGER_PORT", "8040"))
LEASE_TIMEOUT = int(os.environ.get("GPU45_RESOURCE_LEASE_TIMEOUT", "90"))
LOCK = threading.RLock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS leases (
              lease_id TEXT PRIMARY KEY, job_id TEXT NOT NULL, kind TEXT NOT NULL,
              priority INTEGER NOT NULL, preemptible INTEGER NOT NULL,
              resume_policy TEXT NOT NULL, status TEXT NOT NULL,
              requested_at TEXT NOT NULL, acquired_at TEXT, heartbeat_at TEXT,
              released_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_gpu_lease
              ON leases(status) WHERE status = 'active';
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
              lease_id TEXT, job_id TEXT, details_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS state (
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            """
        )
        db.execute("INSERT OR IGNORE INTO state(key,value) VALUES('reclaimed_leases','0')")


def event(db: sqlite3.Connection, event_type: str, lease_id: str | None, job_id: str | None, **details: object) -> None:
    db.execute(
        "INSERT INTO events(event_type,lease_id,job_id,details_json,created_at) VALUES(?,?,?,?,?)",
        (event_type, lease_id, job_id, json.dumps(details), now()),
    )


def service_active(service: str) -> bool:
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", service], check=False).returncode == 0
    except OSError:
        return False


def service_action(action: str, service: str) -> None:
    subprocess.run(["systemctl", action, service], check=True, timeout=90)


def post_local(url: str, payload: dict | None = None) -> None:
    request = urllib.request.Request(url, data=json.dumps(payload or {}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=30):
        pass


def transition_before_grant(db: sqlite3.Connection, row: sqlite3.Row) -> None:
    metadata = json.loads(row["metadata_json"] or "{}")
    stopped = []
    if row["kind"] != "llm" and service_active("llama-openai.service"):
        service_action("stop", "llama-openai.service"); stopped.append("llama-openai.service")
    metadata["stoppedServices"] = stopped
    db.execute("UPDATE leases SET metadata_json=? WHERE lease_id=?", (json.dumps(metadata), row["lease_id"]))


def restore_after_release(db: sqlite3.Connection, row: sqlite3.Row) -> None:
    metadata = json.loads(row["metadata_json"] or "{}")
    for service in metadata.get("stoppedServices", []):
        service_action("start", service)
    resume_tts = db.execute("SELECT value FROM state WHERE key='resume_tts'").fetchone()
    if resume_tts and resume_tts[0] == "1":
        service_action("start", "qwen3-tts-api.service")
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                post_local("http://127.0.0.1:8000/resource/resume")
                break
            except Exception:
                time.sleep(1)
        db.execute("DELETE FROM state WHERE key='resume_tts'")


def preempt_active(db: sqlite3.Connection, active: sqlite3.Row, incoming_priority: int) -> bool:
    if not active["preemptible"] or incoming_priority <= active["priority"]:
        return False
    if active["kind"] == "tts":
        try:
            post_local("http://127.0.0.1:8000/resource/pause", {"reason": "Higher-priority Codex or foreground GPU request"})
        except Exception:
            pass
        if service_active("qwen3-tts-api.service"):
            service_action("stop", "qwen3-tts-api.service")
        db.execute("INSERT OR REPLACE INTO state(key,value) VALUES('resume_tts','1')")
    db.execute("UPDATE leases SET status='interrupted', released_at=? WHERE lease_id=?", (now(), active["lease_id"]))
    event(db, "lease.preempted", active["lease_id"], active["job_id"], incomingPriority=incoming_priority)
    return True


def reclaim_expired(db: sqlite3.Connection) -> int:
    cutoff = time.time() - LEASE_TIMEOUT
    reclaimed = 0
    for row in db.execute("SELECT * FROM leases WHERE status='active'").fetchall():
        heartbeat = row["heartbeat_at"] or row["acquired_at"]
        try:
            stamp = datetime.fromisoformat(heartbeat).timestamp()
        except (TypeError, ValueError):
            stamp = 0
        if stamp < cutoff:
            db.execute("UPDATE leases SET status='interrupted', released_at=? WHERE lease_id=?", (now(), row["lease_id"]))
            event(db, "lease.reclaimed", row["lease_id"], row["job_id"], reason="heartbeat expired")
            reclaimed += 1
    if reclaimed:
        current = int(db.execute("SELECT value FROM state WHERE key='reclaimed_leases'").fetchone()[0])
        db.execute("UPDATE state SET value=? WHERE key='reclaimed_leases'", (str(current + reclaimed),))
    return reclaimed


def grant_next(db: sqlite3.Connection) -> sqlite3.Row | None:
    active = db.execute("SELECT * FROM leases WHERE status='active'").fetchone()
    if active:
        return active
    queued = db.execute(
        "SELECT * FROM leases WHERE status='queued' ORDER BY priority DESC, requested_at ASC LIMIT 1"
    ).fetchone()
    if not queued:
        return None
    try:
        transition_before_grant(db, queued)
    except Exception as exc:
        db.execute("UPDATE leases SET status='interrupted', released_at=? WHERE lease_id=?", (now(), queued["lease_id"]))
        event(db, "lease.transition_failed", queued["lease_id"], queued["job_id"], error=str(exc))
        return grant_next(db)
    stamp = now()
    db.execute(
        "UPDATE leases SET status='active', acquired_at=?, heartbeat_at=? WHERE lease_id=?",
        (stamp, stamp, queued["lease_id"]),
    )
    event(db, "lease.acquired", queued["lease_id"], queued["job_id"], priority=queued["priority"])
    return db.execute("SELECT * FROM leases WHERE lease_id=?", (queued["lease_id"],)).fetchone()


def row_dict(row: sqlite3.Row, queued: bool = False) -> dict[str, object]:
    result = {
        "leaseId" if not queued else "requestId": row["lease_id"],
        "jobId": row["job_id"], "kind": row["kind"], "priority": row["priority"],
        "preemptible": bool(row["preemptible"]), "resumePolicy": row["resume_policy"],
    }
    if queued:
        result.update(requestedAt=row["requested_at"], waitReason="Waiting for the current GPU owner")
    else:
        result.update(acquiredAt=row["acquired_at"], heartbeatAt=row["heartbeat_at"])
    return result


def read_vram() -> dict[str, int | None]:
    candidates = list(Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"))
    for total_path in candidates:
        used_path = total_path.with_name("mem_info_vram_used")
        try:
            total, used = int(total_path.read_text().strip()), int(used_path.read_text().strip())
            if total > 0:
                return {"usedBytes": used, "totalBytes": total, "freeBytes": max(0, total - used)}
        except (OSError, ValueError):
            continue
    return {"usedBytes": None, "totalBytes": None, "freeBytes": None}


def state() -> dict[str, object]:
    with LOCK, connect() as db:
        reclaim_expired(db)
        owner = grant_next(db)
        queue = db.execute("SELECT * FROM leases WHERE status='queued' ORDER BY priority DESC, requested_at").fetchall()
        suspended = db.execute("SELECT * FROM leases WHERE status='suspended' ORDER BY priority DESC, requested_at").fetchall()
        reclaimed = int(db.execute("SELECT value FROM state WHERE key='reclaimed_leases'").fetchone()[0])
        last = db.execute("SELECT event_type || ' at ' || created_at FROM events ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "status": "busy" if owner else "ready", "owner": row_dict(owner) if owner else None,
            "queue": [row_dict(item, True) for item in queue],
            "suspended": [row_dict(item, True) for item in suspended],
            "vram": read_vram(),
            "recovery": {"reclaimedLeases": reclaimed, "lastEvent": last[0] if last else None},
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "GPU45ResourceManager/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)

    def authorized(self) -> bool:
        return bool(TOKEN) and self.headers.get("Authorization", "") == f"Bearer {TOKEN}"

    def body(self) -> dict[str, object]:
        size = min(int(self.headers.get("Content-Length", "0")), 65536)
        return json.loads(self.rfile.read(size) or b"{}")

    def send_json(self, status_code: int, payload: object) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def require_auth(self) -> bool:
        if self.authorized():
            return True
        self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return False

    def do_GET(self) -> None:
        if not self.require_auth():
            return
        if urlparse(self.path).path == "/v1/state":
            self.send_json(HTTPStatus.OK, state())
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if not self.require_auth():
            return
        path = urlparse(self.path).path
        try:
            payload = self.body()
            with LOCK, connect() as db:
                reclaim_expired(db)
                if path == "/v1/leases/acquire":
                    lease_id = str(uuid.uuid4())
                    priority = max(0, min(100, int(payload.get("priority", 10))))
                    stamp = now()
                    db.execute(
                        "INSERT INTO leases(lease_id,job_id,kind,priority,preemptible,resume_policy,status,requested_at,metadata_json) VALUES(?,?,?,?,?,?,?,?,?)",
                        (lease_id, str(payload["jobId"]), str(payload["kind"]), priority,
                         int(bool(payload.get("preemptible", False))), str(payload.get("resumePolicy", "restart")),
                         "queued", stamp, json.dumps(payload.get("metadata", {}))),
                    )
                    event(db, "lease.queued", lease_id, str(payload["jobId"]), priority=priority)
                    active = db.execute("SELECT * FROM leases WHERE status='active'").fetchone()
                    if active:
                        preempt_active(db, active, priority)
                    owner = grant_next(db)
                    granted = bool(owner and owner["lease_id"] == lease_id)
                    self.send_json(HTTPStatus.OK if granted else HTTPStatus.ACCEPTED, {
                        "granted": granted, "leaseId": lease_id,
                    })
                    return
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["v1", "leases"]:
                    lease_id, action = parts[2], parts[3]
                    lease = db.execute("SELECT * FROM leases WHERE lease_id=?", (lease_id,)).fetchone()
                    if not lease:
                        self.send_json(HTTPStatus.NOT_FOUND, {"error": "lease not found"}); return
                    if action == "heartbeat" and lease["status"] == "active":
                        db.execute("UPDATE leases SET heartbeat_at=? WHERE lease_id=?", (now(), lease_id))
                        self.send_json(HTTPStatus.OK, {"ok": True}); return
                    if action == "release":
                        db.execute("UPDATE leases SET status='released', released_at=? WHERE lease_id=?", (now(), lease_id))
                        event(db, "lease.released", lease_id, lease["job_id"])
                        restore_after_release(db, lease)
                        grant_next(db)
                        self.send_json(HTTPStatus.OK, {"ok": True}); return
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("GPU45_RESOURCE_MANAGER_TOKEN must be set")
    init_db()
    print(f"GPU45 resource manager listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
