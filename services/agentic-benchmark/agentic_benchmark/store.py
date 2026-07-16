from __future__ import annotations

import json
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
            return rows

    def campaign_detail(self, campaign_id: str) -> dict[str, Any] | None:
        with self.session() as db:
            campaign = db.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            if not campaign:
                return None
            runs = [dict(row) for row in db.execute("SELECT * FROM runs WHERE campaign_id=? ORDER BY created_at", (campaign_id,))]
            events = [dict(row) for row in db.execute("SELECT * FROM events WHERE campaign_id=? ORDER BY id DESC LIMIT 100", (campaign_id,))]
            return {"campaign": dict(campaign), "runs": runs, "ranking": ranking_rows(runs), "events": events}

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
            return bool(result.rowcount)

    def _event(self, db: sqlite3.Connection, campaign_id: str | None, run_id: str | None, task_id: str | None, event_type: str, message: str, details: dict[str, Any]) -> None:
        db.execute("INSERT INTO events(campaign_id,run_id,task_id,event_type,message,details_json,created_at) VALUES(?,?,?,?,?,?,?)", (campaign_id, run_id, task_id, event_type, message, json.dumps(details, sort_keys=True), now()))
