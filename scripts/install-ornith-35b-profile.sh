#!/usr/bin/env bash
set -euo pipefail

APP_ROOT=${APP_ROOT:-/opt/gpu45-provider-appliance}
MODEL_ROOT=${MODEL_ROOT:-/models/huggingface/staging/deepreinforce-ai--Ornith-1.0-35B-GGUF/main}
HF_BIN=${HF_BIN:-/opt/gpu45-image-venv/bin/hf}
REPO=deepreinforce-ai/Ornith-1.0-35B-GGUF
QUANT=${1:-Q5_K_M}
DB_PATH=${DATABASE_PATH:-/var/lib/gpu45/appliance.db}

case "$QUANT" in
  Q4_K_M|Q5_K_M) ;;
  *) echo "Supported Ornith quants: Q4_K_M or Q5_K_M" >&2; exit 2 ;;
esac

filename="ornith-1.0-35b-${QUANT}.gguf"
model_path="$MODEL_ROOT/$filename"
mkdir -p "$MODEL_ROOT"
if [[ ! -s "$model_path" ]]; then
  "$HF_BIN" download "$REPO" "$filename" --local-dir "$MODEL_ROOT"
fi

python3 - "$DB_PATH" "$model_path" "$REPO" <<'PY'
import hashlib
import sqlite3
import sys
import uuid
from pathlib import Path

db_path, raw_path, repo = sys.argv[1:]
model_path = str(Path(raw_path).resolve())
name = Path(model_path).name
size = Path(model_path).stat().st_size
stem = Path(model_path).stem
alias = f"{stem}-{hashlib.sha1(model_path.encode()).hexdigest()[:8]}"
profile_name = f"gpu45-{stem.lower().replace('_', '-').replace('.', '-')[:64]}-{hashlib.sha1(model_path.encode()).hexdigest()[:8]}"
description = f"Ornith 1.0 35B MoE {stem.rsplit('-', 1)[-1]} reasoning model, text-only, 256K context"

with sqlite3.connect(db_path) as db:
    db.execute(
        """
        INSERT INTO ModelAsset
          (id, name, path, repo, sizeBytes, multimodal, active, served, servedAlias, defaultModel, createdAt, updatedAt)
        VALUES (?, ?, ?, ?, ?, 0, 0, 1, ?, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(path) DO UPDATE SET
          name=excluded.name, repo=excluded.repo, sizeBytes=excluded.sizeBytes,
          multimodal=0, served=1, servedAlias=COALESCE(ModelAsset.servedAlias, excluded.servedAlias),
          updatedAt=CURRENT_TIMESTAMP
        """,
        (uuid.uuid4().hex, name, model_path, repo, size, alias),
    )
    db.execute(
        """
        INSERT INTO LaunchProfile
          (id, name, description, modelPath, host, port, ctxSize, gpuLayers,
           batchSize, uBatchSize, cacheRamMiB, cacheTypeK, cacheTypeV, cacheReuse,
           specType, specDraftNMax, flashAttention, imageMinTokens, metrics, jinja,
           active, backend, fanBoostOnBusy, createdAt, updatedAt)
        VALUES (?, ?, ?, ?, '127.0.0.1', 30000, 262144, 'all',
                4096, 1024, 8192, 'q4_0', 'q4_0', 1024,
                'none', 2, 'on', 1024, 1, 1, 0, 'rocm', 0,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(name) DO UPDATE SET
          description=excluded.description, modelPath=excluded.modelPath, ctxSize=262144,
          gpuLayers='all', batchSize=4096, uBatchSize=1024, cacheTypeK='q4_0',
          cacheTypeV='q4_0', specType='none', flashAttention='on', backend='rocm',
          updatedAt=CURRENT_TIMESTAMP
        """,
        (uuid.uuid4().hex, profile_name, description, model_path),
    )
    db.commit()

print(f"registered_model={model_path}")
print(f"served_alias={alias}")
print(f"launch_profile={profile_name}")
PY
