from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

COMMON_WEIGHTS = {
    "swe-verified-mini50": 0.35,
    "terminal-bench-2": 0.30,
    "bfcl-v4-local": 0.20,
    "tau-text-base": 0.15,
}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"queued", "running", "pausing", "paused", "restoring"}
QUALITY_WINDOW = 0.05
EFFICIENCY_TIE_WINDOW = 3.0


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def configuration_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def composite_score(scores: dict[str, float | None]) -> float | None:
    if any(scores.get(suite_id) is None for suite_id in COMMON_WEIGHTS):
        return None
    return round(sum(float(scores[suite_id]) * weight for suite_id, weight in COMMON_WEIGHTS.items()), 6)


def load_suite_manifests(directory: Path) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        suite_id = str(payload.get("id", "")).strip()
        if not suite_id or suite_id in seen:
            raise ValueError(f"Invalid or duplicate suite id in {path}")
        if not isinstance(payload.get("requiresDocker"), bool):
            raise ValueError(f"Suite {suite_id} must declare requiresDocker")
        seen.add(suite_id)
        payload["manifestHash"] = configuration_hash(payload)
        manifests.append(payload)
    return manifests


def ranking_rows(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_profile: dict[str, dict[str, Any]] = {}
    for run in runs:
        if run.get("track") != "controlled":
            continue
        profile = str(run["profile_name"])
        row = by_profile.setdefault(profile, {"profileName": profile, "scores": {}, "invalidOutputRate": 0.0})
        if run.get("status") == "completed":
            row["scores"][run["suite_id"]] = run.get("score")
        row["invalidOutputRate"] = max(row["invalidOutputRate"], float(run.get("invalid_output_rate") or 0))
    for row in by_profile.values():
        row["compositeScore"] = composite_score(row["scores"])
    return sorted(
        by_profile.values(),
        key=lambda row: (
            row["compositeScore"] is not None,
            row["compositeScore"] or -1,
            row["scores"].get("swe-verified-mini50") or -1,
            row["scores"].get("terminal-bench-2") or -1,
            -(row["invalidOutputRate"] or 0),
        ),
        reverse=True,
    )


def efficiency_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"rows": [], "panelLeaderSolves": 0, "qualityLeaderScore": None, "tie": False}
    quality_scores = [float(row["qualityScore"]) for row in rows if row.get("qualityScore") is not None]
    quality_leader = max(quality_scores, default=None)
    panel_leader = max((int(row.get("successes") or 0) for row in rows), default=0)
    normalized = []
    for source in rows:
        row = dict(source)
        successes = int(row.get("successes") or 0)
        quality = row.get("qualityScore")
        row["qualityEligible"] = quality_leader is not None and quality is not None and float(quality) >= quality_leader - QUALITY_WINDOW
        row["solveEligible"] = successes > 0 and successes >= panel_leader - 1
        row["measurementComplete"] = bool(row.get("measurementComplete"))
        row["eligible"] = row["qualityEligible"] and row["solveEligible"] and row["measurementComplete"]
        row["timePerSolveMs"] = float(row.get("activeInferenceMs") or 0) / successes if successes else None
        row["tokensPerSolve"] = float(row.get("totalTokens") or 0) / successes if successes else None
        incremental = float(row.get("incrementalEnergyWh") or 0)
        gross = float(row.get("grossEnergyWh") or 0)
        energy = incremental if incremental > 0 else gross
        row["energyBasis"] = "incremental" if incremental > 0 else "gross"
        row["energyPerSolveWh"] = energy / successes if successes and energy > 0 else None
        row["efficiencyIndex"] = None
        normalized.append(row)

    eligible = [row for row in normalized if row["eligible"] and row["timePerSolveMs"] and row["tokensPerSolve"] and row["energyPerSolveWh"]]
    if eligible:
        best_time = min(row["timePerSolveMs"] for row in eligible)
        best_tokens = min(row["tokensPerSolve"] for row in eligible)
        best_energy = min(row["energyPerSolveWh"] for row in eligible)
        for row in eligible:
            time_factor = min(1.0, best_time / row["timePerSolveMs"])
            token_factor = min(1.0, best_tokens / row["tokensPerSolve"])
            energy_factor = min(1.0, best_energy / row["energyPerSolveWh"])
            row["timeFactor"] = time_factor
            row["tokenFactor"] = token_factor
            row["energyFactor"] = energy_factor
            row["efficiencyIndex"] = round(100.0 * time_factor**0.50 * energy_factor**0.30 * token_factor**0.20, 3)

    normalized.sort(
        key=lambda row: (row.get("efficiencyIndex") is not None, row.get("efficiencyIndex") or -1, row.get("successes") or 0),
        reverse=True,
    )
    for index, row in enumerate(normalized, start=1):
        row["rank"] = index if row.get("efficiencyIndex") is not None else None
    scored = [row for row in normalized if row.get("efficiencyIndex") is not None]
    tie = len(scored) > 1 and float(scored[0]["efficiencyIndex"]) - float(scored[1]["efficiencyIndex"]) <= EFFICIENCY_TIE_WINDOW
    return {
        "rows": normalized,
        "panelLeaderSolves": panel_leader,
        "qualityLeaderScore": quality_leader,
        "tie": tie,
        "confirmationRecommended": tie,
    }
