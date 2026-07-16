from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .domain import configuration_hash


PROFILE_FIELDS = (
    "name", "description", "modelPath", "mmprojPath", "modelDraftPath", "ctxSize", "gpuLayers",
    "batchSize", "uBatchSize", "cacheRamMiB", "cacheTypeK", "cacheTypeV", "cacheReuse", "specType",
    "specDraftNMax", "flashAttention", "backend", "serverBinary", "runtimeLibraryPath", "imageMinTokens",
    "metrics", "jinja",
)


def _sidecar_checksum(model_path: Path) -> str | None:
    candidates = [model_path.with_suffix(model_path.suffix + ".sha256"), model_path.with_suffix(".sha256")]
    for candidate in candidates:
        try:
            value = candidate.read_text(encoding="utf-8").strip().split()[0]
        except (OSError, IndexError):
            continue
        if len(value) == 64 and all(character in "0123456789abcdefABCDEF" for character in value):
            return value.lower()
    return None


def discover_profiles(database_path: Path) -> list[dict[str, Any]]:
    if not database_path.exists():
        return []
    db = sqlite3.connect(database_path)
    db.row_factory = sqlite3.Row
    try:
        profile_columns = {row[1] for row in db.execute("PRAGMA table_info(LaunchProfile)")}
        asset_columns = {row[1] for row in db.execute("PRAGMA table_info(ModelAsset)")}
        if not {"name", "modelPath"}.issubset(profile_columns):
            return []
        select_fields = [field for field in PROFILE_FIELDS if field in profile_columns]
        asset_join = {"path", "served"}.issubset(asset_columns)
        alias_select = ", m.servedAlias AS servedAlias" if "servedAlias" in asset_columns else ", NULL AS servedAlias"
        if asset_join:
            query = f"SELECT {', '.join('p.' + field for field in select_fields)}{alias_select} FROM LaunchProfile p JOIN ModelAsset m ON m.path=p.modelPath WHERE m.served=1 ORDER BY p.name"
        else:
            query = f"SELECT {', '.join(select_fields)}, name AS servedAlias FROM LaunchProfile ORDER BY name"
        rows = db.execute(query).fetchall()
    finally:
        db.close()

    profiles: list[dict[str, Any]] = []
    for row in rows:
        snapshot = dict(row)
        model_path = Path(str(snapshot["modelPath"]))
        if not model_path.is_file():
            continue
        stat = model_path.stat()
        snapshot.update(
            modelSizeBytes=stat.st_size,
            modelModifiedNs=stat.st_mtime_ns,
            modelChecksum=_sidecar_checksum(model_path),
            modelAvailable=True,
        )
        snapshot["profileHash"] = configuration_hash(snapshot)
        profiles.append(snapshot)
    return profiles


def snapshot_json(profile: dict[str, Any]) -> str:
    return json.dumps(profile, sort_keys=True, separators=(",", ":"))
