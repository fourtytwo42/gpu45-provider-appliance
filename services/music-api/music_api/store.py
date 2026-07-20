from __future__ import annotations

import json
import sqlite3
import statistics
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MusicStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def initialize(self) -> None:
        with self.lock, self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(
                  id TEXT PRIMARY KEY,profile_id TEXT NOT NULL,mode TEXT NOT NULL,task_type TEXT NOT NULL,
                  status TEXT NOT NULL,stage TEXT NOT NULL,progress REAL NOT NULL DEFAULT 0,
                  eta_seconds INTEGER,payload_json TEXT NOT NULL,assets_json TEXT NOT NULL DEFAULT '{}',
                  metrics_json TEXT NOT NULL DEFAULT '{}',error TEXT,process_pid INTEGER,
                  cancel_requested INTEGER NOT NULL DEFAULT 0,recovery_state TEXT,
                  created_at TEXT NOT NULL,updated_at TEXT NOT NULL,started_at TEXT,completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_status_created_idx ON jobs(status,created_at);
                CREATE TABLE IF NOT EXISTS events(
                  id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT,event_type TEXT NOT NULL,
                  details_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_job_idx ON events(job_id,id);
                CREATE TABLE IF NOT EXISTS licenses(
                  license_id TEXT NOT NULL,license_hash TEXT NOT NULL,accepted_by TEXT NOT NULL,
                  accepted_at TEXT NOT NULL,PRIMARY KEY(license_id,license_hash,accepted_by)
                );
                """
            )
            db.execute("INSERT OR REPLACE INTO metadata VALUES('schema_version','1')")

    def recover(self) -> int:
        stamp = now_iso()
        with self.lock, self.connect() as db:
            rows = db.execute("SELECT id,profile_id FROM jobs WHERE status IN ('running','waiting','restoring')").fetchall()
            for row in rows:
                restart = "restart" if str(row["profile_id"]).startswith("ace-") else "resume-phase"
                db.execute(
                    "UPDATE jobs SET status='queued',stage='recovered',progress=0,process_pid=NULL,recovery_state=?,updated_at=? WHERE id=?",
                    (restart, stamp, row["id"]),
                )
                self._event(db, row["id"], "job.recovered", {"policy": restart})
            return len(rows)

    def _event(self, db: sqlite3.Connection, job_id: str | None, event_type: str, details: dict[str, object] | None = None) -> None:
        db.execute(
            "INSERT INTO events(job_id,event_type,details_json,created_at) VALUES(?,?,?,?)",
            (job_id, event_type, json.dumps(details or {}), now_iso()),
        )

    def create_job(
        self, profile_id: str, mode: str, task_type: str, payload: dict[str, object], *, status: str = "queued",
    ) -> dict[str, object]:
        job_id = str(uuid.uuid4())
        stamp = now_iso()
        with self.lock, self.connect() as db:
            db.execute(
                "INSERT INTO jobs(id,profile_id,mode,task_type,status,stage,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (job_id, profile_id, mode, task_type, status, status, json.dumps(payload), stamp, stamp),
            )
            self._event(db, job_id, "job.created", {"profileId": profile_id, "mode": mode, "taskType": task_type})
        return self.get_job(job_id) or {}

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, object]:
        value = dict(row)
        value["payload"] = json.loads(value.pop("payload_json") or "{}")
        value["assets"] = json.loads(value.pop("assets_json") or "{}")
        value["metrics"] = json.loads(value.pop("metrics_json") or "{}")
        value["cancel_requested"] = bool(value["cancel_requested"])
        return value

    def get_job(self, job_id: str) -> dict[str, object] | None:
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return self._decode(row) if row else None

    def list_jobs(self, limit: int = 100, offset: int = 0, status: str | None = None) -> list[dict[str, object]]:
        with self.lock, self.connect() as db:
            if status:
                rows = db.execute("SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC LIMIT ? OFFSET ?", (status, limit, offset)).fetchall()
            else:
                rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            return [self._decode(row) for row in rows]

    def next_queued(self) -> dict[str, object] | None:
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            return self._decode(row) if row else None

    def estimate_seconds(self, profile_id: str, task_type: str, duration: float) -> int | None:
        samples: list[tuple[float, float]] = []
        for job in self.list_jobs(250, status="completed"):
            if job["profile_id"] != profile_id or job["task_type"] != task_type:
                continue
            generation_seconds = job["metrics"].get("generationSeconds")
            sample_duration = job["payload"].get("duration")
            try:
                generation_seconds = float(generation_seconds)
                sample_duration = float(sample_duration)
            except (TypeError, ValueError):
                continue
            if generation_seconds > 0 and sample_duration > 0:
                samples.append((sample_duration, generation_seconds))
        if not samples:
            return None
        samples = sorted(samples[:12])
        exact = [seconds for sample_duration, seconds in samples if abs(sample_duration - duration) < 0.01]
        if exact:
            return max(1, round(statistics.median(exact)))
        lower = [sample for sample in samples if sample[0] < duration]
        upper = [sample for sample in samples if sample[0] > duration]
        if lower and upper:
            left_duration, left_seconds = lower[-1]
            right_duration, right_seconds = upper[0]
            fraction = (duration - left_duration) / (right_duration - left_duration)
            return max(1, round(left_seconds + (right_seconds - left_seconds) * fraction))
        sample_duration, generation_seconds = min(samples, key=lambda sample: abs(sample[0] - duration))
        ratio = duration / sample_duration
        return max(1, round(generation_seconds * (0.75 + 0.25 * ratio)))

    def update(self, job_id: str, **values: object) -> dict[str, object]:
        allowed = {
            "status", "stage", "progress", "eta_seconds", "assets_json", "metrics_json", "error",
            "process_pid", "cancel_requested", "recovery_state", "started_at", "completed_at",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return self.get_job(job_id) or {}
        updates["updated_at"] = now_iso()
        assignments = ",".join(f"{key}=?" for key in updates)
        with self.lock, self.connect() as db:
            cursor = db.execute(f"UPDATE jobs SET {assignments} WHERE id=?", (*updates.values(), job_id))
            if cursor.rowcount != 1:
                raise KeyError(job_id)
        return self.get_job(job_id) or {}

    def request_cancel(self, job_id: str) -> dict[str, object]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] == "queued":
            return self.update(job_id, status="cancelled", stage="cancelled", progress=100, cancel_requested=1, completed_at=now_iso())
        return self.update(job_id, cancel_requested=1, stage="cancelling")

    def mark_interrupted(self, job_id: str) -> dict[str, object]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        policy = "restart" if str(job["profile_id"]).startswith("ace-") else "resume-phase"
        stamp = now_iso()
        with self.lock, self.connect() as db:
            db.execute(
                "UPDATE jobs SET status='queued',stage='recovered',progress=0,eta_seconds=NULL,"
                "process_pid=NULL,recovery_state=?,updated_at=? WHERE id=?",
                (policy, stamp, job_id),
            )
            self._event(db, job_id, "job.interrupted", {"policy": policy})
        return self.get_job(job_id) or {}

    def retry(self, job_id: str) -> dict[str, object]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        if job["status"] not in {"failed", "cancelled"}:
            raise ValueError("Only failed or cancelled music jobs can be retried.")
        return self.update(
            job_id,status="queued",stage="queued",progress=0,eta_seconds=None,error=None,
            process_pid=None,cancel_requested=0,completed_at=None,recovery_state="retry",
        )

    def delete(self, job_id: str) -> dict[str, object] | None:
        job = self.get_job(job_id)
        if not job:
            return None
        if job["status"] in {"running", "waiting", "restoring"}:
            raise ValueError("Cancel the active music job before deleting it.")
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM events WHERE job_id=?", (job_id,))
            db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        return job

    def accept_license(self, license_id: str, license_hash: str, accepted_by: str) -> None:
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO licenses VALUES(?,?,?,?)", (license_id, license_hash, accepted_by, now_iso()))

    def license_accepted(self, license_id: str, license_hash: str, accepted_by: str = "hendo420") -> bool:
        with self.lock, self.connect() as db:
            return db.execute("SELECT 1 FROM licenses WHERE license_id=? AND license_hash=? AND accepted_by=?", (license_id, license_hash, accepted_by)).fetchone() is not None
