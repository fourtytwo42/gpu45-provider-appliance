from __future__ import annotations

import json
import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain import COMMON_WEIGHTS, configuration_hash, efficiency_rows, ranking_rows


EFFICIENCY_SUITE_WEIGHTS = {
    "bfcl-efficiency-v1": 0.20,
    "tau-efficiency-v1": 0.15,
    "swe-efficiency-v1": 0.35,
    "terminal-efficiency-v1": 0.30,
}


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

    def create_efficiency_campaign(
        self,
        campaign_id: str,
        profiles: list[dict[str, Any]],
        suites: list[dict[str, Any]],
        confirmation: bool = False,
    ) -> str | None:
        detail = self.campaign_detail(campaign_id)
        if not detail or detail["campaign"]["status"] != "completed" or detail["campaign"]["preset"] != "common":
            return None
        top = [row for row in detail["ranking"] if row.get("compositeScore") is not None][:3]
        if len(top) < 3:
            return None
        link_type = "efficiency-confirmation" if confirmation else "efficiency"
        if confirmation:
            report = self.efficiency_report(campaign_id)
            if not report or not report.get("tie"):
                return None
            top = report["rows"][:2]
            profile_names = {row["profileName"] for row in top}
        else:
            profile_names = {row["profileName"] for row in top}
        required_ids = {"bfcl-efficiency-v1", "tau-efficiency-v1", "swe-efficiency-v1", "terminal-efficiency-v1"}
        selected_profiles = [profile for profile in profiles if profile["name"] in profile_names]
        selected_suites = [suite for suite in suites if suite["id"] in required_ids]
        expected_profiles = 2 if confirmation else 3
        if len(selected_profiles) != expected_profiles or {suite["id"] for suite in selected_suites} != required_ids:
            return None
        with self.session() as db:
            existing = db.execute(
                "SELECT target_campaign_id FROM campaign_links WHERE source_campaign_id=? AND link_type=?",
                (campaign_id, link_type),
            ).fetchone()
            if existing:
                return str(existing["target_campaign_id"])
        target_id = self.create_campaign(
            f"{'Confirmation' if confirmation else 'Finalist'} efficiency panel for {detail['campaign']['name']}",
            "efficiency-confirmation-v1" if confirmation else "efficiency-v1",
            selected_profiles,
            selected_suites,
        )
        with self.session() as db:
            db.execute(
                "INSERT OR IGNORE INTO campaign_links(source_campaign_id,target_campaign_id,link_type,created_at) VALUES(?,?,?,?)",
                (campaign_id, target_id, link_type, now()),
            )
            self._event(
                db, campaign_id, None, None, "campaign.efficiency_queued",
                "Queued finalist efficiency panel" if not confirmation else "Queued efficiency confirmation",
                {"targetCampaignId": target_id, "profiles": sorted(profile_names)},
            )
        return target_id

    def create_reference_campaign(
        self,
        campaign_id: str,
        profiles: list[dict[str, Any]],
        suites: list[dict[str, Any]],
    ) -> str | None:
        source = self.campaign_detail(campaign_id)
        if not source or source["campaign"]["preset"] != "common" or len(profiles) != 1:
            return None
        selected_suites = [suite for suite in suites if suite["id"] in EFFICIENCY_SUITE_WEIGHTS]
        if {suite["id"] for suite in selected_suites} != set(EFFICIENCY_SUITE_WEIGHTS):
            return None
        with self.session() as db:
            existing = db.execute(
                "SELECT target_campaign_id FROM campaign_links WHERE source_campaign_id=? AND link_type='reference'",
                (campaign_id,),
            ).fetchone()
            if existing:
                return str(existing["target_campaign_id"])
        profile = profiles[0]
        target_id = self.create_campaign(
            f"{profile.get('displayName') or profile['name']} reference for {source['campaign']['name']}",
            "agent-system-reference-v1",
            profiles,
            selected_suites,
        )
        with self.session() as db:
            db.execute("UPDATE runs SET track='reference' WHERE campaign_id=?", (target_id,))
            db.execute(
                "INSERT OR IGNORE INTO campaign_links(source_campaign_id,target_campaign_id,link_type,created_at) VALUES(?,?,?,?)",
                (campaign_id, target_id, "reference", now()),
            )
            self._event(
                db, campaign_id, None, None, "campaign.reference_queued",
                "Queued Codex agent-system reference panel",
                {"targetCampaignId": target_id, "profile": profile["name"]},
            )
        return target_id

    def _reference_report(self, campaign_id: str) -> dict[str, Any]:
        empty = {
            "referenceCampaignId": None,
            "referenceStatus": "not_started",
            "referenceRows": [],
        }
        with self.session() as db:
            link = db.execute(
                "SELECT target_campaign_id FROM campaign_links WHERE source_campaign_id=? AND link_type='reference'",
                (campaign_id,),
            ).fetchone()
            if not link:
                return empty
            target_id = str(link["target_campaign_id"])
            campaign = db.execute("SELECT status FROM campaigns WHERE id=?", (target_id,)).fetchone()
            run_rows = [dict(row) for row in db.execute(
                """
                SELECT r.profile_name,r.profile_snapshot_json,r.suite_id,r.status,r.score,r.expected_tasks,
                       SUM(CASE WHEN t.status IN ('completed','failed') THEN 1 ELSE 0 END) completed_tasks,
                       SUM(CASE WHEN t.status='completed' AND t.passed=1 THEN 1 ELSE 0 END) successes,
                       COALESCE(SUM(t.prompt_tokens),0) prompt_tokens,
                       COALESCE(SUM(t.completion_tokens),0) completion_tokens,
                       COALESCE(SUM(m.active_inference_ms),0) active_inference_ms,
                       COALESCE(SUM(m.wall_duration_ms),0) wall_duration_ms,
                       COALESCE(SUM(m.response_calls),0) response_calls,
                       COALESCE(SUM(m.tool_calls),0) tool_calls,
                       COALESCE(SUM(m.invalid_calls),0) invalid_calls,
                       SUM(CASE WHEN m.measurement_status='complete' THEN 1 ELSE 0 END) measured_tasks
                FROM runs r
                LEFT JOIN tasks t ON t.run_id=r.id
                LEFT JOIN task_measurements m ON m.task_id=t.id AND m.attempt=t.attempt
                WHERE r.campaign_id=?
                GROUP BY r.id
                ORDER BY r.created_at
                """,
                (target_id,),
            )]
        by_profile: dict[str, dict[str, Any]] = {}
        for run in run_rows:
            snapshot = json.loads(run["profile_snapshot_json"])
            row = by_profile.setdefault(run["profile_name"], {
                "profileName": run["profile_name"],
                "displayName": snapshot.get("displayName") or run["profile_name"],
                "systemType": "agent-system-reference",
                "model": snapshot.get("model"),
                "reasoningEffort": snapshot.get("reasoningEffort"),
                "expectedTasks": 0,
                "completedTasks": 0,
                "successes": 0,
                "promptTokens": 0,
                "completionTokens": 0,
                "activeInferenceMs": 0,
                "wallDurationMs": 0,
                "responseCalls": 0,
                "toolCalls": 0,
                "invalidCalls": 0,
                "measuredTasks": 0,
                "suiteScores": {},
                "allRunsCompleted": True,
                "energyAvailable": False,
            })
            for source_key, target_key in (
                ("expected_tasks", "expectedTasks"), ("completed_tasks", "completedTasks"),
                ("successes", "successes"), ("prompt_tokens", "promptTokens"),
                ("completion_tokens", "completionTokens"), ("active_inference_ms", "activeInferenceMs"),
                ("wall_duration_ms", "wallDurationMs"), ("response_calls", "responseCalls"),
                ("tool_calls", "toolCalls"), ("invalid_calls", "invalidCalls"),
                ("measured_tasks", "measuredTasks"),
            ):
                row[target_key] += int(run[source_key] or 0)
            row["allRunsCompleted"] = row["allRunsCompleted"] and run["status"] == "completed"
            if run["status"] == "completed" and run["score"] is not None:
                row["suiteScores"][run["suite_id"]] = float(run["score"])
        rows = []
        for row in by_profile.values():
            total_tokens = row["promptTokens"] + row["completionTokens"]
            all_scores = set(row["suiteScores"]) == set(EFFICIENCY_SUITE_WEIGHTS)
            panel_score = round(sum(row["suiteScores"][suite] * weight for suite, weight in EFFICIENCY_SUITE_WEIGHTS.items()), 6) if all_scores else None
            successes = row["successes"]
            row.update(
                panelScore=panel_score,
                totalTokens=total_tokens,
                timePerSolveMs=row["activeInferenceMs"] / successes if successes else None,
                tokensPerSolve=total_tokens / successes if successes else None,
                measurementComplete=row["completedTasks"] > 0 and row["completedTasks"] == row["expectedTasks"] and row["measuredTasks"] == row["completedTasks"],
            )
            rows.append(row)
        return {
            "referenceCampaignId": target_id,
            "referenceStatus": str(campaign["status"]) if campaign else "missing",
            "referenceRows": rows,
        }

    def efficiency_report(self, campaign_id: str) -> dict[str, Any] | None:
        source = self.campaign_detail(campaign_id)
        if not source:
            return None
        reference = self._reference_report(campaign_id)
        with self.session() as db:
            link = db.execute(
                "SELECT target_campaign_id FROM campaign_links WHERE source_campaign_id=? AND link_type='efficiency'",
                (campaign_id,),
            ).fetchone()
            if not link:
                return {
                    "sourceCampaignId": campaign_id,
                    "campaignId": None,
                    "status": "not_started",
                    "rows": [],
                    "tie": False,
                    "confirmationRecommended": False,
                    **reference,
                }
            target_id = str(link["target_campaign_id"])
            target = db.execute("SELECT * FROM campaigns WHERE id=?", (target_id,)).fetchone()
            aggregates = [dict(row) for row in db.execute(
                """
                SELECT r.profile_name,
                       COALESCE(SUM(r.expected_tasks),0) expected_tasks,
                       COUNT(t.id) task_rows,
                       SUM(CASE WHEN t.status IN ('completed','failed') THEN 1 ELSE 0 END) completed_tasks,
                       SUM(CASE WHEN t.status='completed' AND t.passed=1 THEN 1 ELSE 0 END) successes,
                       COALESCE(SUM(t.prompt_tokens),0) prompt_tokens,
                       COALESCE(SUM(t.completion_tokens),0) completion_tokens,
                       COALESCE(SUM(m.active_inference_ms),0) active_inference_ms,
                       COALESCE(SUM(m.wall_duration_ms),0) wall_duration_ms,
                       COALESCE(SUM(m.gross_energy_wh),0) gross_energy_wh,
                       COALESCE(SUM(m.incremental_energy_wh),0) incremental_energy_wh,
                       COALESCE(SUM(m.response_calls),0) response_calls,
                       COALESCE(SUM(m.tool_calls),0) tool_calls,
                       COALESCE(SUM(m.invalid_calls),0) invalid_calls,
                       SUM(CASE WHEN m.measurement_status='complete' THEN 1 ELSE 0 END) measured_tasks,
                       MAX(m.peak_power_w) peak_power_w,
                       MAX(m.peak_gpu_temp_c) peak_gpu_temp_c,
                       MAX(m.peak_vram_bytes) peak_vram_bytes,
                       MAX(m.peak_ram_bytes) peak_ram_bytes
                FROM runs r
                LEFT JOIN tasks t ON t.run_id=r.id
                LEFT JOIN task_measurements m ON m.task_id=t.id AND m.attempt=t.attempt
                WHERE r.campaign_id=?
                GROUP BY r.profile_name
                """,
                (target_id,),
            )]
            panel_runs = [dict(row) for row in db.execute(
                "SELECT profile_name,suite_id,status,score FROM runs WHERE campaign_id=?",
                (target_id,),
            )]
        quality = {row["profileName"]: row.get("compositeScore") for row in source["ranking"]}
        panel_scores: dict[str, dict[str, float]] = {}
        for panel_run in panel_runs:
            if panel_run["status"] == "completed" and panel_run["score"] is not None:
                panel_scores.setdefault(panel_run["profile_name"], {})[panel_run["suite_id"]] = float(panel_run["score"])
        rows = []
        for aggregate in aggregates:
            completed = int(aggregate["completed_tasks"] or 0)
            prompt_tokens = int(aggregate["prompt_tokens"] or 0)
            completion_tokens = int(aggregate["completion_tokens"] or 0)
            profile_scores = panel_scores.get(aggregate["profile_name"], {})
            panel_score = round(sum(profile_scores[suite] * weight for suite, weight in EFFICIENCY_SUITE_WEIGHTS.items()), 6) if set(profile_scores) == set(EFFICIENCY_SUITE_WEIGHTS) else None
            rows.append({
                "profileName": aggregate["profile_name"],
                "qualityScore": quality.get(aggregate["profile_name"]),
                "panelScore": panel_score,
                "expectedTasks": int(aggregate["expected_tasks"] or 0),
                "completedTasks": completed,
                "successes": int(aggregate["successes"] or 0),
                "promptTokens": prompt_tokens,
                "completionTokens": completion_tokens,
                "totalTokens": prompt_tokens + completion_tokens,
                "activeInferenceMs": int(aggregate["active_inference_ms"] or 0),
                "wallDurationMs": int(aggregate["wall_duration_ms"] or 0),
                "grossEnergyWh": float(aggregate["gross_energy_wh"] or 0),
                "incrementalEnergyWh": float(aggregate["incremental_energy_wh"] or 0),
                "responseCalls": int(aggregate["response_calls"] or 0),
                "toolCalls": int(aggregate["tool_calls"] or 0),
                "invalidCalls": int(aggregate["invalid_calls"] or 0),
                "peakPowerW": aggregate["peak_power_w"],
                "peakGpuTempC": aggregate["peak_gpu_temp_c"],
                "peakVramBytes": aggregate["peak_vram_bytes"],
                "peakRamBytes": aggregate["peak_ram_bytes"],
                "measurementComplete": completed > 0 and completed == int(aggregate["expected_tasks"] or 0) and int(aggregate["measured_tasks"] or 0) == completed,
            })
        report = efficiency_rows(rows)
        return {
            "sourceCampaignId": campaign_id,
            "campaignId": target_id,
            "status": str(target["status"]) if target else "missing",
            **reference,
            **report,
        }

    def run_baseline(self, run_id: str) -> dict[str, Any] | None:
        with self.session() as db:
            row = db.execute("SELECT * FROM run_baselines WHERE run_id=?", (run_id,)).fetchone()
            return dict(row) if row else None

    def record_run_baseline(self, run_id: str, measurement: dict[str, Any]) -> None:
        with self.session() as db:
            db.execute(
                "INSERT OR REPLACE INTO run_baselines(run_id,idle_power_w,duration_seconds,sample_count,measured_at) VALUES(?,?,?,?,?)",
                (run_id, float(measurement.get("idle_power_w") or 0), float(measurement.get("duration_seconds") or 0), int(measurement.get("sample_count") or 0), now()),
            )

    def record_task_measurement(self, task_id: str, attempt: int, measurement: dict[str, Any]) -> None:
        stamp = now()
        with self.session() as db:
            task = db.execute("SELECT run_id,status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                return
            requests = db.execute(
                """
                SELECT COUNT(*) response_calls,COALESCE(SUM(tool_calls),0) tool_calls,
                       COALESCE(SUM(prompt_tokens),0) prompt_tokens,COALESCE(SUM(completion_tokens),0) completion_tokens,
                       COALESCE(SUM(cached_tokens),0) cached_tokens,COALESCE(SUM(reasoning_tokens),0) reasoning_tokens,
                       COALESCE(SUM(duration_ms),0) active_inference_ms,
                       SUM(CASE WHEN completed=0 OR status_code>=400 THEN 1 ELSE 0 END) invalid_calls,
                       SUM(CASE WHEN usage_source='missing' THEN 1 ELSE 0 END) missing_usage
                FROM request_metrics WHERE task_id=? AND attempt=?
                """,
                (task_id, attempt),
            ).fetchone()
            response_calls = int(requests["response_calls"] or 0)
            prompt_tokens = int(requests["prompt_tokens"] or 0)
            completion_tokens = int(requests["completion_tokens"] or 0)
            measurement_status = "complete" if response_calls > 0 and int(requests["missing_usage"] or 0) == 0 else "incomplete"
            db.execute(
                """
                INSERT INTO task_measurements(
                  task_id,attempt,wall_duration_ms,active_inference_ms,response_calls,tool_calls,invalid_calls,
                  prompt_tokens,completion_tokens,cached_tokens,reasoning_tokens,idle_power_w,gross_energy_wh,
                  incremental_energy_wh,peak_power_w,peak_gpu_temp_c,peak_vram_bytes,peak_ram_bytes,sample_count,
                  measurement_status,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id,attempt) DO UPDATE SET
                  wall_duration_ms=excluded.wall_duration_ms,active_inference_ms=excluded.active_inference_ms,
                  response_calls=excluded.response_calls,tool_calls=excluded.tool_calls,invalid_calls=excluded.invalid_calls,
                  prompt_tokens=excluded.prompt_tokens,completion_tokens=excluded.completion_tokens,cached_tokens=excluded.cached_tokens,
                  reasoning_tokens=excluded.reasoning_tokens,idle_power_w=excluded.idle_power_w,
                  gross_energy_wh=excluded.gross_energy_wh,incremental_energy_wh=excluded.incremental_energy_wh,
                  peak_power_w=excluded.peak_power_w,peak_gpu_temp_c=excluded.peak_gpu_temp_c,
                  peak_vram_bytes=excluded.peak_vram_bytes,peak_ram_bytes=excluded.peak_ram_bytes,
                  sample_count=excluded.sample_count,measurement_status=excluded.measurement_status,updated_at=excluded.updated_at
                """,
                (
                    task_id, attempt, int(measurement.get("wall_duration_ms") or 0), int(requests["active_inference_ms"] or 0),
                    response_calls, int(requests["tool_calls"] or 0), int(requests["invalid_calls"] or 0),
                    prompt_tokens, completion_tokens, int(requests["cached_tokens"] or 0), int(requests["reasoning_tokens"] or 0),
                    float(measurement.get("idle_power_w") or 0), float(measurement.get("gross_energy_wh") or 0),
                    float(measurement.get("incremental_energy_wh") or 0), measurement.get("peak_power_w"),
                    measurement.get("peak_gpu_temp_c"), measurement.get("peak_vram_bytes"), measurement.get("peak_ram_bytes"),
                    int(measurement.get("sample_count") or 0), measurement_status, stamp, stamp,
                ),
            )
            if int(attempt) == int(db.execute("SELECT attempt FROM tasks WHERE id=?", (task_id,)).fetchone()[0]):
                db.execute(
                    "UPDATE tasks SET prompt_tokens=?,completion_tokens=?,steps=?,updated_at=? WHERE id=?",
                    (prompt_tokens, completion_tokens, max(response_calls, int(requests["tool_calls"] or 0)), stamp, task_id),
                )
            self._refresh_run(db, task["run_id"], incomplete_status="queued" if task["status"] == "interrupted" else "running")

    def retry_campaign_infrastructure(self, campaign_id: str) -> int:
        """Queue failed infrastructure tasks as a fresh user-requested attempt."""
        stamp = now()
        with self.session() as db:
            failed_runs = db.execute(
                "SELECT r.id FROM runs r WHERE r.campaign_id=? AND r.status='failed' AND r.error IS NOT NULL "
                "AND (r.completed_tasks=0 OR EXISTS (SELECT 1 FROM tasks t WHERE t.run_id=r.id AND t.status IN ('queued','interrupted')))",
                (campaign_id,),
            ).fetchall()
            deduped_run_ids = {
                row["id"] for row in db.execute("SELECT id FROM runs WHERE campaign_id=?", (campaign_id,)).fetchall()
                if self._dedupe_run_tasks(db, row["id"])
            }
            rows = db.execute(
                "SELECT t.id,t.run_id FROM tasks t JOIN runs r ON r.id=t.run_id WHERE r.campaign_id=? AND t.error_class='infrastructure_failure' AND t.status='completed'",
                (campaign_id,),
            ).fetchall()
            if not rows and not failed_runs:
                for run_id in deduped_run_ids:
                    self._refresh_run(db, run_id, incomplete_status="queued")
                return 0
            task_ids = [row["id"] for row in rows]
            run_ids = sorted({row["run_id"] for row in rows})
            db.executemany(
                "UPDATE tasks SET status='queued',attempt=attempt+1,passed=NULL,reward=NULL,duration_ms=0,error_class=NULL,user_message=NULL,technical_error=NULL,started_at=NULL,completed_at=NULL,updated_at=? WHERE id=?",
                [(stamp, task_id) for task_id in task_ids],
            )
            db.executemany(
                "UPDATE runs SET error=NULL,infrastructure_failures=0,completed_at=NULL,updated_at=? WHERE id=?",
                [(stamp, run_id) for run_id in run_ids],
            )
            for run_id in run_ids:
                # Keep already scored tasks visible. Only the infrastructure
                # failures above are reset for another attempt.
                self._refresh_run(db, run_id, incomplete_status="queued")
            db.executemany(
                "UPDATE runs SET status='interrupted',error=NULL,infrastructure_failures=0,completed_at=NULL,updated_at=? WHERE id=?",
                [(stamp, row["id"]) for row in failed_runs],
            )
            for run_id in {row["id"] for row in failed_runs}:
                self._refresh_run(db, run_id, incomplete_status="interrupted")
            for run_id in deduped_run_ids - set(run_ids) - {row["id"] for row in failed_runs}:
                self._refresh_run(db, run_id, incomplete_status="queued")
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
                SELECT r.*,c.status campaign_status,c.preset campaign_preset,c.pause_requested,c.cancel_requested,c.previous_profile_name
                FROM runs r JOIN campaigns c ON c.id=r.campaign_id
                WHERE c.status='queued' AND c.pause_requested=0 AND c.cancel_requested=0
                  AND r.status IN ('queued','interrupted')
                ORDER BY
                  CASE c.preset
                    WHEN 'agent-system-reference-v1' THEN 0
                    ELSE 1
                  END,
                  c.created_at,
                  CASE WHEN r.status='interrupted' THEN 0 ELSE 1 END,
                  r.created_at
                LIMIT 1
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
            self._dedupe_run_tasks(db, run_id)
            existing = db.execute("SELECT id,external_task_id FROM tasks WHERE run_id=?", (run_id,)).fetchall()
            stale_ids = [row["id"] for row in existing if row["external_task_id"] not in desired]
            if stale_ids:
                db.executemany("DELETE FROM artifacts WHERE task_id=?", [(task_id,) for task_id in stale_ids])
                db.executemany("DELETE FROM tasks WHERE id=?", [(task_id,) for task_id in stale_ids])
            existing_ids = {row["external_task_id"] for row in existing if row["external_task_id"] in desired}
            for external_id in (item for item in external_task_ids if item not in existing_ids):
                db.execute(
                    "INSERT INTO tasks(id,run_id,external_task_id,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (str(uuid.uuid4()), run_id, external_id, stamp, stamp),
                )
            db.execute(
                "UPDATE runs SET expected_tasks=?,updated_at=? WHERE campaign_id=? AND suite_id=?",
                (len(external_task_ids), stamp, run["campaign_id"], run["suite_id"]),
            )
            self._refresh_run(db, run_id)

    @staticmethod
    def _dedupe_run_tasks(db: sqlite3.Connection, run_id: str) -> int:
        """Remove legacy duplicate rows while retaining the newest attempt for each case."""
        rows = db.execute(
            "SELECT id,external_task_id,attempt,updated_at FROM tasks WHERE run_id=? "
            "ORDER BY external_task_id,attempt DESC,updated_at DESC,id DESC",
            (run_id,),
        ).fetchall()
        seen: set[str] = set()
        stale_ids: list[str] = []
        for row in rows:
            external_id = str(row["external_task_id"])
            if external_id in seen:
                stale_ids.append(str(row["id"]))
            else:
                seen.add(external_id)
        if stale_ids:
            db.executemany("DELETE FROM tasks WHERE id=?", [(task_id,) for task_id in stale_ids])
        return len(stale_ids)

    def next_task(self, run_id: str) -> dict[str, Any] | None:
        with self.session() as db:
            row = db.execute("SELECT * FROM tasks WHERE run_id=? AND status IN ('queued','interrupted') ORDER BY created_at LIMIT 1", (run_id,)).fetchone()
            return dict(row) if row else None

    def begin_task(self, task_id: str) -> dict[str, Any]:
        stamp = now()
        with self.session() as db:
            db.execute(
                "UPDATE tasks SET attempt=CASE WHEN status='interrupted' THEN attempt+1 ELSE attempt END,"
                "status='running',error_class=NULL,user_message=NULL,technical_error=NULL,started_at=?,completed_at=NULL,updated_at=? WHERE id=?",
                (stamp, stamp, task_id),
            )
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not task:
                raise ValueError("task not found")
            return dict(task)

    def record_request_metric(self, payload: dict[str, Any]) -> bool:
        required = ("campaignId", "runId", "taskId", "attempt", "requestId", "apiPath", "statusCode")
        if any(payload.get(key) is None for key in required):
            raise ValueError("Incomplete benchmark request metric")
        with self.session() as db:
            task = db.execute(
                "SELECT t.attempt,t.run_id,r.campaign_id FROM tasks t JOIN runs r ON r.id=t.run_id WHERE t.id=?",
                (str(payload["taskId"]),),
            ).fetchone()
            if not task or task["run_id"] != str(payload["runId"]) or task["campaign_id"] != str(payload["campaignId"]):
                raise ValueError("Benchmark request correlation does not match a task")
            db.execute(
                """
                INSERT OR IGNORE INTO request_metrics(
                  id,campaign_id,run_id,task_id,attempt,request_id,model,requested_model,api_path,status_code,
                  prompt_tokens,completion_tokens,cached_tokens,reasoning_tokens,duration_ms,tool_calls,usage_source,completed,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()), str(payload["campaignId"]), str(payload["runId"]), str(payload["taskId"]),
                    int(payload["attempt"]), str(payload["requestId"]), payload.get("model"), payload.get("requestedModel"),
                    str(payload["apiPath"]), int(payload["statusCode"]), max(0, int(payload.get("promptTokens") or 0)),
                    max(0, int(payload.get("completionTokens") or 0)), max(0, int(payload.get("cachedTokens") or 0)),
                    max(0, int(payload.get("reasoningTokens") or 0)), max(0, int(payload.get("durationMs") or 0)),
                    max(0, int(payload.get("toolCalls") or 0)), str(payload.get("usageSource") or "response"),
                    int(bool(payload.get("completed"))), str(payload.get("createdAt") or now()),
                ),
            )
            return bool(db.execute("SELECT changes()").fetchone()[0])

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
                """
                SELECT t.*,r.profile_name,r.suite_id,
                       m.active_inference_ms,m.response_calls,m.tool_calls,m.invalid_calls,m.cached_tokens,m.reasoning_tokens,
                       m.idle_power_w,m.gross_energy_wh,m.incremental_energy_wh,m.peak_power_w,
                       m.peak_gpu_temp_c measurement_peak_gpu_temp_c,m.peak_vram_bytes measurement_peak_vram_bytes,
                       m.peak_ram_bytes,m.sample_count,m.measurement_status
                FROM tasks t JOIN runs r ON r.id=t.run_id
                LEFT JOIN task_measurements m ON m.task_id=t.id AND m.attempt=t.attempt
                WHERE r.campaign_id=? ORDER BY r.profile_name,r.suite_id,t.external_task_id
                """,
                (campaign_id,),
            )]
            artifacts = [dict(row) for row in db.execute("SELECT * FROM artifacts WHERE campaign_id=? ORDER BY created_at", (campaign_id,))]
            requests = [dict(row) for row in db.execute("SELECT * FROM request_metrics WHERE campaign_id=? ORDER BY created_at", (campaign_id,))]
        return {**detail, "tasks": tasks, "requestMetrics": requests, "artifacts": artifacts}

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
        resources = db.execute(
            """
            SELECT COALESCE(SUM(t.prompt_tokens+t.completion_tokens),0) total_tokens,
                   COALESCE(SUM(t.duration_ms),0) duration_ms,
                   MAX(m.peak_gpu_temp_c) peak_gpu_temp_c,
                   MAX(m.peak_vram_bytes) peak_vram_bytes
            FROM tasks t
            LEFT JOIN task_measurements m ON m.task_id=t.id AND m.attempt=t.attempt
            WHERE t.run_id=? AND t.status IN ('completed','failed')
            """,
            (run_id,),
        ).fetchone()
        expected = int(db.execute("SELECT expected_tasks FROM runs WHERE id=?", (run_id,)).fetchone()[0])
        done = int(counts["done"] or 0)
        status = "completed" if expected > 0 and done >= expected else incomplete_status
        score = float(counts["score"]) if counts["score"] is not None else None
        db.execute(
            "UPDATE runs SET status=?,completed_tasks=?,passed_tasks=?,failed_tasks=?,score=?,total_tokens=?,duration_ms=?,"
            "peak_gpu_temp_c=?,peak_vram_bytes=?,completed_at=CASE WHEN ?='completed' THEN ? ELSE completed_at END,updated_at=? WHERE id=?",
            (
                status, done, int(counts["passed"] or 0), int(counts["failed"] or 0), score,
                int(resources["total_tokens"] or 0), int(resources["duration_ms"] or 0), resources["peak_gpu_temp_c"],
                resources["peak_vram_bytes"], status, stamp, stamp, run_id,
            ),
        )
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
