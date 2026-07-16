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
