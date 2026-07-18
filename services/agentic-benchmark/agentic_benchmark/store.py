from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain import COMMON_WEIGHTS, configuration_hash, ranking_rows


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BenchmarkStore:
    def __init__(self, database_path: Path, schema_path: Path):
        self.database_path = database_path
        self.schema_path = schema_path

    def connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.database_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        return db

    @contextmanager
    def session(self):
        db = self.connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self) -> None:
        with self.session() as db:
            db.executescript(self.schema_path.read_text(encoding="utf-8"))
            stamp = now()
            db.execute("UPDATE tasks SET status='interrupted', error_class='service_restart', updated_at=? WHERE status='running'", (stamp,))
            db.execute("UPDATE runs SET status='queued', lease_id=NULL, updated_at=? WHERE status IN ('running','restoring')", (stamp,))
            db.execute("UPDATE campaigns SET status='queued', current_run_id=NULL, updated_at=? WHERE status IN ('running','restoring')", (stamp,))
            cancelled = [row[0] for row in db.execute("SELECT id FROM campaigns WHERE cancel_requested=1 AND status NOT IN ('completed','failed','cancelled')")]
            for campaign_id in cancelled:
                db.execute("UPDATE tasks SET status='cancelled',error_class=COALESCE(error_class,'cancelled'),completed_at=COALESCE(completed_at,?),updated_at=? WHERE run_id IN (SELECT id FROM runs WHERE campaign_id=?) AND status NOT IN ('completed','failed','cancelled')", (stamp, stamp, campaign_id))
                db.execute("UPDATE runs SET status='cancelled',completed_at=COALESCE(completed_at,?),updated_at=? WHERE campaign_id=? AND status NOT IN ('completed','failed','cancelled')", (stamp, stamp, campaign_id))
                db.execute("UPDATE campaigns SET status='cancelled',current_run_id=NULL,completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?", (stamp, stamp, campaign_id))

    def sync_qualifications(self, profiles: list[dict[str, Any]]) -> list[str]:
        pending: list[str] = []
        stamp = now()
        with self.session() as db:
            for profile in profiles:
                row = db.execute("SELECT profile_hash,status FROM model_qualifications WHERE profile_name=?", (profile["name"],)).fetchone()
                changed = row is None or row["profile_hash"] != profile["profileHash"]
                if changed:
                    pending.append(profile["name"])
                db.execute(
                    """
                    INSERT INTO model_qualifications(profile_name,profile_hash,model_path,model_checksum,status,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(profile_name) DO UPDATE SET
                      profile_hash=excluded.profile_hash, model_path=excluded.model_path,
                      model_checksum=excluded.model_checksum,
                      status=CASE WHEN model_qualifications.profile_hash<>excluded.profile_hash THEN 'pending' ELSE model_qualifications.status END,
                      remediation=CASE WHEN model_qualifications.profile_hash<>excluded.profile_hash THEN NULL ELSE model_qualifications.remediation END,
                      updated_at=excluded.updated_at
                    """,
                    (profile["name"], profile["profileHash"], profile["modelPath"], profile.get("modelChecksum"), "pending", stamp, stamp),
                )
        return pending

    def list_qualifications(self) -> list[dict[str, Any]]:
        with self.session() as db:
            return [dict(row) for row in db.execute("SELECT * FROM model_qualifications ORDER BY profile_name")]

    def pending_qualification_names(self) -> list[str]:
        with self.session() as db:
            return [row[0] for row in db.execute("SELECT profile_name FROM model_qualifications WHERE status IN ('pending','interrupted') ORDER BY updated_at")]

    def retry_qualification(self, profile_name: str) -> bool:
        with self.session() as db:
            result = db.execute(
                "UPDATE model_qualifications SET status='pending',remediation=NULL,last_smoke_campaign_id=NULL,updated_at=? WHERE profile_name=?",
                (now(), profile_name),
            )
            return bool(result.rowcount)

    def ensure_smoke_campaign(self, profile: dict[str, Any], suite: dict[str, Any]) -> str | None:
        with self.session() as db:
            qualification = db.execute(
                "SELECT status,last_smoke_campaign_id FROM model_qualifications WHERE profile_name=? AND profile_hash=?",
                (profile["name"], profile["profileHash"]),
            ).fetchone()
            if not qualification or qualification["status"] not in {"pending", "interrupted"}:
                return None
            if qualification["last_smoke_campaign_id"]:
                campaign = db.execute("SELECT status FROM campaigns WHERE id=?", (qualification["last_smoke_campaign_id"],)).fetchone()
                if campaign and campaign["status"] not in {"completed", "failed", "cancelled"}:
                    return str(qualification["last_smoke_campaign_id"])
        campaign_id = self.create_campaign(
            f"Compatibility smoke: {profile['name']}", "automatic-model-smoke", [profile], [suite]
        )
        with self.session() as db:
            db.execute(
                "UPDATE model_qualifications SET status='queued',last_smoke_campaign_id=?,updated_at=? WHERE profile_name=?",
                (campaign_id, now(), profile["name"]),
            )
        return campaign_id

    def create_campaign(self, name: str, preset: str, profiles: list[dict[str, Any]], suites: list[dict[str, Any]]) -> str:
        if not profiles or not suites:
            raise ValueError("A campaign requires at least one model and one suite")
        campaign_id = str(uuid.uuid4())
        stamp = now()
        config = {
            "preset": preset,
            "profiles": [{"name": profile["name"], "profileHash": profile["profileHash"]} for profile in profiles],
            "suites": [{"id": suite["id"], "manifestHash": suite["manifestHash"]} for suite in suites],
            "weights": COMMON_WEIGHTS,
        }
        with self.session() as db:
            db.execute(
                "INSERT INTO campaigns(id,name,preset,model_profiles_json,suite_ids_json,ranking_policy_json,configuration_hash,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (campaign_id, name, preset, json.dumps(config["profiles"]), json.dumps([suite["id"] for suite in suites]), json.dumps(COMMON_WEIGHTS), configuration_hash(config), stamp, stamp),
            )
            for profile in profiles:
                for suite in suites:
                    db.execute(
                        """
                        INSERT INTO runs(id,campaign_id,profile_name,profile_snapshot_json,profile_hash,suite_id,suite_snapshot_json,track,expected_tasks,created_at,updated_at)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (str(uuid.uuid4()), campaign_id, profile["name"], json.dumps(profile, sort_keys=True), profile["profileHash"], suite["id"], json.dumps(suite, sort_keys=True), "controlled", int(suite.get("taskCount") or 0), stamp, stamp),
                    )
            self._event(db, campaign_id, None, None, "campaign.created", f"Created {name}", config)
        return campaign_id

    def list_campaigns(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.session() as db:
            rows = [dict(row) for row in db.execute("SELECT * FROM campaigns ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 200)),))]
            for row in rows:
                counts = db.execute("SELECT status,COUNT(*) count FROM runs WHERE campaign_id=? GROUP BY status", (row["id"],)).fetchall()
                row["runSummary"] = {count["status"]: count["count"] for count in counts}
                progress = db.execute(
                    "SELECT COALESCE(SUM(expected_tasks),0) total,COALESCE(SUM(completed_tasks),0) completed FROM runs WHERE campaign_id=?",
                    (row["id"],),
                ).fetchone()
                row["progress"] = {"completed": int(progress["completed"]), "total": int(progress["total"])}
            return rows

    def campaign_detail(self, campaign_id: str) -> dict[str, Any] | None:
        with self.session() as db:
            campaign = db.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            if not campaign:
                return None
            runs = [dict(row) for row in db.execute("SELECT * FROM runs WHERE campaign_id=? ORDER BY created_at", (campaign_id,))]
            events = [dict(row) for row in db.execute("SELECT * FROM events WHERE campaign_id=? ORDER BY id DESC LIMIT 100", (campaign_id,))]
            artifacts = [dict(row) for row in db.execute(
                "SELECT id,run_id,task_id,kind,relative_path,size_bytes,created_at FROM artifacts WHERE campaign_id=? ORDER BY created_at DESC LIMIT 200",
                (campaign_id,),
            )]
            return {"campaign": dict(campaign), "runs": runs, "ranking": ranking_rows(runs), "events": events, "artifacts": artifacts}

    def promote_top_three(self, campaign_id: str, profiles: list[dict[str, Any]], suites: list[dict[str, Any]]) -> str | None:
        """Create one qualification campaign for the top three complete common-campaign models."""
        detail = self.campaign_detail(campaign_id)
        if not detail or detail["campaign"]["status"] != "completed" or detail["campaign"]["preset"] != "common":
            return None
        top = [row for row in detail["ranking"] if row.get("compositeScore") is not None][:3]
        if len(top) < 3:
            return None
        profile_names = {row["profileName"] for row in top}
        selected_profiles = [profile for profile in profiles if profile["name"] in profile_names]
        required_ids = {
            "swe-bench-verified-500", "tau-three-trial-reliability",
            "bfcl-failed-category-rerun", "gpu45-codex-acceptance",
        }
        selected_suites = [suite for suite in suites if suite["id"] in required_ids]
        if len(selected_profiles) != 3 or {suite["id"] for suite in selected_suites} != required_ids:
            return None
        state_key = f"qualification:{campaign_id}"
        with self.session() as db:
            existing = db.execute("SELECT value FROM coordinator_state WHERE key=?", (state_key,)).fetchone()
            if existing:
                return str(existing["value"])
        qualification_id = self.create_campaign(
            f"Top-three qualification for {detail['campaign']['name']}",
            "top-three-qualification", selected_profiles, selected_suites,
        )
        with self.session() as db:
            db.execute(
                "INSERT OR IGNORE INTO coordinator_state(key,value,updated_at) VALUES(?,?,?)",
                (state_key, qualification_id, now()),
            )
            self._event(db, campaign_id, None, None, "campaign.promoted", "Queued top-three qualification", {"qualificationCampaignId": qualification_id, "profiles": sorted(profile_names)})
        return qualification_id

    def retry_campaign_infrastructure(self, campaign_id: str) -> int:
        """Queue failed infrastructure tasks as a fresh user-requested attempt."""
        stamp = now()
        with self.session() as db:
            rows = db.execute(
                "SELECT t.id,t.run_id FROM tasks t JOIN runs r ON r.id=t.run_id WHERE r.campaign_id=? AND t.error_class='infrastructure_failure' AND t.status='completed'",
                (campaign_id,),
            ).fetchall()
            failed_runs = db.execute(
                "SELECT id FROM runs WHERE campaign_id=? AND status='failed' AND completed_tasks=0 AND error IS NOT NULL",
                (campaign_id,),
            ).fetchall()
            if not rows and not failed_runs:
                return 0
            task_ids = [row["id"] for row in rows]
            run_ids = sorted({row["run_id"] for row in rows})
            db.executemany(
                "UPDATE tasks SET status='queued',attempt=1,passed=NULL,reward=NULL,duration_ms=0,error_class=NULL,user_message=NULL,technical_error=NULL,started_at=NULL,completed_at=NULL,updated_at=? WHERE id=?",
                [(stamp, task_id) for task_id in task_ids],
            )
            db.executemany(
                "UPDATE runs SET error=NULL,completed_at=NULL,updated_at=? WHERE id=?",
                [(stamp, run_id) for run_id in run_ids],
            )
            for run_id in run_ids:
                # Keep already scored tasks visible. Only the infrastructure
                # failures above are reset for another attempt.
                self._refresh_run(db, run_id, incomplete_status="queued")
            db.executemany(
                "UPDATE runs SET status='interrupted',error=NULL,completed_at=NULL,updated_at=? WHERE id=?",
                [(stamp, row["id"]) for row in failed_runs],
            )
            db.execute("UPDATE campaigns SET status='queued',completed_at=NULL,updated_at=? WHERE id=?", (stamp, campaign_id))
            retried = len(task_ids) + len(failed_runs)
            self._event(db, campaign_id, None, None, "campaign.infrastructure_retry", f"Queued {retried} infrastructure failures", {})
            return retried

    def retry_run_infrastructure(self, run_id: str, error: str, max_attempts: int = 2) -> bool:
        stamp = now()
        with self.session() as db:
            run = db.execute("SELECT campaign_id,infrastructure_failures FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                return False
            attempts = int(run["infrastructure_failures"] or 0) + 1
            if attempts > max_attempts:
                return False
            db.execute(
                "UPDATE runs SET status='interrupted',infrastructure_failures=?,error=?,lease_id=NULL,updated_at=? WHERE id=?",
                (attempts, error, stamp, run_id),
            )
            db.execute("UPDATE campaigns SET status='queued',current_run_id=NULL,updated_at=? WHERE id=?", (stamp, run["campaign_id"]))
            self._event(db, run["campaign_id"], run_id, None, "run.infrastructure_retry", f"Infrastructure retry {attempts}/{max_attempts}", {"error": error})
            return True

    def list_tasks(self, campaign_id: str, cursor: int = 0, limit: int = 50) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 200))
        safe_cursor = max(0, cursor)
        with self.session() as db:
            total = db.execute("SELECT COUNT(*) FROM tasks t JOIN runs r ON r.id=t.run_id WHERE r.campaign_id=?", (campaign_id,)).fetchone()[0]
            rows = [dict(row) for row in db.execute("SELECT t.*,r.profile_name,r.suite_id FROM tasks t JOIN runs r ON r.id=t.run_id WHERE r.campaign_id=? ORDER BY t.created_at LIMIT ? OFFSET ?", (campaign_id, safe_limit, safe_cursor))]
        return {"items": rows, "cursor": safe_cursor, "nextCursor": safe_cursor + len(rows) if safe_cursor + len(rows) < total else None, "total": total}

    def set_campaign_action(self, campaign_id: str, action: str) -> bool:
        stamp = now()
        fields = {
            "start": ("status='queued',pause_requested=0,cancel_requested=0", "campaign.started"),
            "pause": ("pause_requested=1", "campaign.pause_requested"),
            "resume": ("status='queued',pause_requested=0,cancel_requested=0", "campaign.resumed"),
            "cancel": ("cancel_requested=1", "campaign.cancel_requested"),
        }
        if action not in fields:
            raise ValueError("Unsupported campaign action")
        assignment, event_type = fields[action]
        with self.session() as db:
            result = db.execute(f"UPDATE campaigns SET {assignment},updated_at=? WHERE id=?", (stamp, campaign_id))
            if result.rowcount:
                self._event(db, campaign_id, None, None, event_type, action.capitalize(), {})
                if action == "cancel":
                    running = db.execute(
                        "SELECT 1 FROM runs WHERE campaign_id=? AND status IN ('running','restoring') LIMIT 1",
                        (campaign_id,),
                    ).fetchone()
                    if not running:
                        db.execute(
                            "UPDATE tasks SET status='cancelled',error_class=COALESCE(error_class,'cancelled'),completed_at=COALESCE(completed_at,?),updated_at=? "
                            "WHERE run_id IN (SELECT id FROM runs WHERE campaign_id=?) AND status NOT IN ('completed','failed','cancelled')",
                            (stamp, stamp, campaign_id),
                        )
                        db.execute(
                            "UPDATE runs SET status='cancelled',completed_at=COALESCE(completed_at,?),updated_at=? "
                            "WHERE campaign_id=? AND status NOT IN ('completed','failed','cancelled')",
                            (stamp, stamp, campaign_id),
                        )
                        db.execute(
                            "UPDATE campaigns SET status='cancelled',current_run_id=NULL,completed_at=COALESCE(completed_at,?),updated_at=? WHERE id=?",
                            (stamp, stamp, campaign_id),
                        )
                        self._event(db, campaign_id, None, None, "campaign.cancelled", "Campaign cancelled while idle", {})
            return bool(result.rowcount)

    def campaign_control(self, campaign_id: str) -> dict[str, Any] | None:
        with self.session() as db:
            row = db.execute(
                "SELECT status,pause_requested,cancel_requested FROM campaigns WHERE id=?",
                (campaign_id,),
            ).fetchone()
            return dict(row) if row else None

    def apply_pending_control(self, campaign_id: str, run_id: str) -> str | None:
        """Apply a requested pause or cancellation at a clean task boundary."""
        stamp = now()
        with self.session() as db:
            control = db.execute(
                "SELECT pause_requested,cancel_requested FROM campaigns WHERE id=?",
                (campaign_id,),
            ).fetchone()
            if not control:
                return "cancelled"
            if control["cancel_requested"]:
                db.execute("UPDATE tasks SET status='cancelled',error_class=CASE WHEN status='running' THEN 'cancelled' ELSE error_class END,completed_at=CASE WHEN status='running' THEN ? ELSE completed_at END,updated_at=? WHERE run_id=? AND status IN ('queued','interrupted','running')", (stamp, stamp, run_id))
                db.execute("UPDATE runs SET status='cancelled',completed_at=?,updated_at=? WHERE id=?", (stamp, stamp, run_id))
                db.execute("UPDATE campaigns SET status='cancelled',current_run_id=NULL,completed_at=?,updated_at=? WHERE id=?", (stamp, stamp, campaign_id))
                self._event(db, campaign_id, run_id, None, "campaign.cancelled", "Campaign cancelled at a task boundary", {})
                return "cancelled"
            if control["pause_requested"]:
                db.execute("UPDATE tasks SET status='interrupted',error_class='paused',updated_at=? WHERE run_id=? AND status='running'", (stamp, run_id))
                db.execute("UPDATE runs SET status='interrupted',updated_at=? WHERE id=?", (stamp, run_id))
                db.execute("UPDATE campaigns SET status='paused',current_run_id=NULL,updated_at=? WHERE id=?", (stamp, campaign_id))
                self._event(db, campaign_id, run_id, None, "campaign.paused", "Campaign paused at a task boundary", {})
                return "paused"
        return None

    def next_runnable(self) -> dict[str, Any] | None:
        with self.session() as db:
            row = db.execute(
                """
                SELECT r.*,c.status campaign_status,c.pause_requested,c.cancel_requested,c.previous_profile_name
                FROM runs r JOIN campaigns c ON c.id=r.campaign_id
                WHERE c.status='queued' AND c.pause_requested=0 AND c.cancel_requested=0
                  AND r.status IN ('queued','interrupted')
                ORDER BY c.created_at,CASE WHEN r.status='interrupted' THEN 0 ELSE 1 END,r.created_at LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def has_pending_profile_runs(self, campaign_id: str, profile_name: str, current_run_id: str) -> bool:
        """Keep a benchmark model warm while its remaining campaign suites run."""
        with self.session() as db:
            row = db.execute(
                "SELECT 1 FROM runs WHERE campaign_id=? AND profile_name=? AND id<>? "
                "AND status IN ('queued','interrupted','running') LIMIT 1",
                (campaign_id, profile_name, current_run_id),
            ).fetchone()
            return row is not None

    def campaign_previous_profile(self, campaign_id: str) -> str | None:
        with self.session() as db:
            row = db.execute("SELECT previous_profile_name FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            return str(row[0]) if row and row[0] else None

    def begin_run(self, run_id: str, previous_profile_name: str | None) -> dict[str, Any]:
        stamp = now()
        with self.session() as db:
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise ValueError("run not found")
            db.execute("UPDATE campaigns SET status='running',current_run_id=?,previous_profile_name=COALESCE(previous_profile_name,?),started_at=COALESCE(started_at,?),updated_at=? WHERE id=?", (run_id, previous_profile_name, stamp, stamp, run["campaign_id"]))
            db.execute("UPDATE runs SET status='running',started_at=COALESCE(started_at,?),updated_at=? WHERE id=?", (stamp, stamp, run_id))
            self._event(db, run["campaign_id"], run_id, None, "run.started", f"Started {run['suite_id']} on {run['profile_name']}", {})
            return dict(run)

    def ensure_tasks(self, run_id: str, external_task_ids: list[str]) -> None:
        stamp = now()
        desired = set(external_task_ids)
        with self.session() as db:
            run = db.execute("SELECT campaign_id,suite_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                raise ValueError("run not found")
            existing = db.execute("SELECT id,external_task_id FROM tasks WHERE run_id=?", (run_id,)).fetchall()
            stale_ids = [row["id"] for row in existing if row["external_task_id"] not in desired]
            if stale_ids:
                db.executemany("DELETE FROM artifacts WHERE task_id=?", [(task_id,) for task_id in stale_ids])
                db.executemany("DELETE FROM tasks WHERE id=?", [(task_id,) for task_id in stale_ids])
            for external_id in external_task_ids:
                db.execute(
                    "INSERT OR IGNORE INTO tasks(id,run_id,external_task_id,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (str(uuid.uuid4()), run_id, external_id, stamp, stamp),
                )
            db.execute(
                "UPDATE runs SET expected_tasks=?,updated_at=? WHERE campaign_id=? AND suite_id=?",
                (len(external_task_ids), stamp, run["campaign_id"], run["suite_id"]),
            )
            self._refresh_run(db, run_id)

    def next_task(self, run_id: str) -> dict[str, Any] | None:
        with self.session() as db:
            row = db.execute("SELECT * FROM tasks WHERE run_id=? AND status IN ('queued','interrupted') ORDER BY created_at LIMIT 1", (run_id,)).fetchone()
            return dict(row) if row else None

    def begin_task(self, task_id: str) -> None:
        stamp = now()
        with self.session() as db:
            db.execute("UPDATE tasks SET status='running',error_class=NULL,user_message=NULL,technical_error=NULL,started_at=?,completed_at=NULL,updated_at=? WHERE id=?", (stamp, stamp, task_id))

    def complete_task(self, task_id: str, passed: bool, duration_ms: int, error_class: str | None = None, user_message: str | None = None, technical_error: str | None = None, reward: float | None = None) -> None:
        stamp = now()
        with self.session() as db:
            task = db.execute("SELECT run_id FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                return
            db.execute(
                "UPDATE tasks SET status=?,passed=?,reward=?,duration_ms=?,error_class=?,user_message=?,technical_error=?,completed_at=?,updated_at=? WHERE id=?",
                ("completed", int(passed), float(reward if reward is not None else (1.0 if passed else 0.0)), duration_ms, error_class, user_message, technical_error, stamp, stamp, task_id),
            )
            self._refresh_run(db, task["run_id"])

    def retry_infrastructure_task(self, task_id: str, message: str) -> bool:
        """Retry one infrastructure failure without changing the model score."""
        stamp = now()
        with self.session() as db:
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task or int(task["attempt"]) >= 2:
                return False
            db.execute(
                "UPDATE tasks SET status='queued',attempt=attempt+1,error_class='infrastructure_retry',user_message=?,technical_error=NULL,started_at=NULL,updated_at=? WHERE id=?",
                (message, stamp, task_id),
            )
            return True

    def add_artifact(self, campaign_id: str, run_id: str | None, task_id: str | None, kind: str, relative_path: str, content: bytes) -> dict[str, Any]:
        artifact_id = str(uuid.uuid4())
        digest = hashlib.sha256(content).hexdigest()
        with self.session() as db:
            db.execute(
                "INSERT INTO artifacts(id,campaign_id,run_id,task_id,kind,relative_path,size_bytes,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (artifact_id, campaign_id, run_id, task_id, kind, relative_path, len(content), digest, now()),
            )
        return {"id": artifact_id, "kind": kind, "relativePath": relative_path, "sizeBytes": len(content), "sha256": digest}

    def register_artifact_path(self, campaign_id: str, run_id: str | None, task_id: str | None, kind: str, relative_path: str, path: Path) -> dict[str, Any]:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        artifact_id = str(uuid.uuid4())
        size = path.stat().st_size
        with self.session() as db:
            db.execute(
                "INSERT INTO artifacts(id,campaign_id,run_id,task_id,kind,relative_path,size_bytes,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (artifact_id, campaign_id, run_id, task_id, kind, relative_path, size, digest.hexdigest(), now()),
            )
        return {"id": artifact_id, "kind": kind, "relativePath": relative_path, "sizeBytes": size, "sha256": digest.hexdigest()}

    def artifact(self, campaign_id: str, artifact_id: str) -> dict[str, Any] | None:
        with self.session() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=? AND campaign_id=?", (artifact_id, campaign_id)).fetchone()
            return dict(row) if row else None

    def export_rows(self, campaign_id: str) -> dict[str, Any] | None:
        detail = self.campaign_detail(campaign_id)
        if not detail:
            return None
        with self.session() as db:
            tasks = [dict(row) for row in db.execute(
                "SELECT t.*,r.profile_name,r.suite_id FROM tasks t JOIN runs r ON r.id=t.run_id WHERE r.campaign_id=? ORDER BY r.profile_name,r.suite_id,t.external_task_id",
                (campaign_id,),
            )]
            artifacts = [dict(row) for row in db.execute("SELECT * FROM artifacts WHERE campaign_id=? ORDER BY created_at", (campaign_id,))]
        return {**detail, "tasks": tasks, "artifacts": artifacts}

    def interrupt_run(self, run_id: str, reason: str) -> None:
        stamp = now()
        with self.session() as db:
            run = db.execute("SELECT campaign_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                return
            db.execute("UPDATE tasks SET status='interrupted',error_class='resource_preempted',updated_at=? WHERE run_id=? AND status='running'", (stamp, run_id))
            db.execute("UPDATE runs SET status='interrupted',lease_id=NULL,updated_at=? WHERE id=?", (stamp, run_id))
            db.execute("UPDATE campaigns SET status='queued',current_run_id=NULL,updated_at=? WHERE id=?", (stamp, run["campaign_id"]))
            self._event(db, run["campaign_id"], run_id, None, "run.interrupted", reason, {})

    def fail_run(self, run_id: str, error: str) -> None:
        stamp = now()
        with self.session() as db:
            run = db.execute("SELECT campaign_id,profile_name,suite_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                return
            db.execute("UPDATE runs SET status='failed',error=?,completed_at=?,updated_at=? WHERE id=?", (error, stamp, stamp, run_id))
            self._finish_campaign_if_ready(db, run["campaign_id"])
            if run["suite_id"] == "gpu45-smoke-v1":
                db.execute("UPDATE model_qualifications SET status='failed',remediation=?,last_checked_at=?,updated_at=? WHERE profile_name=?", (error, stamp, stamp, run["profile_name"]))

    def _refresh_run(self, db: sqlite3.Connection, run_id: str, incomplete_status: str = "running") -> None:
        stamp = now()
        counts = db.execute("SELECT COUNT(*) total,SUM(CASE WHEN status IN ('completed','failed') THEN 1 ELSE 0 END) done,SUM(CASE WHEN status='completed' AND passed=1 THEN 1 ELSE 0 END) passed,SUM(CASE WHEN status IN ('completed','failed') AND COALESCE(passed,0)=0 THEN 1 ELSE 0 END) failed,AVG(CASE WHEN status IN ('completed','failed') THEN reward END) score FROM tasks WHERE run_id=?", (run_id,)).fetchone()
        expected = int(db.execute("SELECT expected_tasks FROM runs WHERE id=?", (run_id,)).fetchone()[0])
        done = int(counts["done"] or 0)
        status = "completed" if expected > 0 and done >= expected else incomplete_status
        score = float(counts["score"]) if counts["score"] is not None else None
        db.execute("UPDATE runs SET status=?,completed_tasks=?,passed_tasks=?,failed_tasks=?,score=?,completed_at=CASE WHEN ?='completed' THEN ? ELSE completed_at END,updated_at=? WHERE id=?", (status, done, int(counts["passed"] or 0), int(counts["failed"] or 0), score, status, stamp, stamp, run_id))
        if status == "completed":
            run = db.execute("SELECT campaign_id,profile_name,suite_id FROM runs WHERE id=?", (run_id,)).fetchone()
            if run["suite_id"] == "gpu45-smoke-v1":
                qualification_status = "eligible" if int(counts["failed"] or 0) == 0 else "failed"
                remediation = None if qualification_status == "eligible" else f"{int(counts['failed'] or 0)} smoke checks failed"
                db.execute("UPDATE model_qualifications SET status=?,remediation=?,last_checked_at=?,updated_at=? WHERE profile_name=?", (qualification_status, remediation, stamp, stamp, run["profile_name"]))
            self._finish_campaign_if_ready(db, run["campaign_id"])

    def _finish_campaign_if_ready(self, db: sqlite3.Connection, campaign_id: str) -> None:
        remaining = db.execute("SELECT COUNT(*) FROM runs WHERE campaign_id=? AND status NOT IN ('completed','failed','cancelled')", (campaign_id,)).fetchone()[0]
        if remaining:
            db.execute("UPDATE campaigns SET status='queued',current_run_id=NULL,updated_at=? WHERE id=?", (now(), campaign_id))
            return
        failures = db.execute("SELECT COUNT(*) FROM runs WHERE campaign_id=? AND status='failed'", (campaign_id,)).fetchone()[0]
        status = "failed" if failures else "completed"
        db.execute("UPDATE campaigns SET status=?,current_run_id=NULL,completed_at=?,updated_at=? WHERE id=?", (status, now(), now(), campaign_id))

    def _event(self, db: sqlite3.Connection, campaign_id: str | None, run_id: str | None, task_id: str | None, event_type: str, message: str, details: dict[str, Any]) -> None:
        db.execute("INSERT INTO events(campaign_id,run_id,task_id,event_type,message,details_json,created_at) VALUES(?,?,?,?,?,?,?)", (campaign_id, run_id, task_id, event_type, message, json.dumps(details, sort_keys=True), now()))
