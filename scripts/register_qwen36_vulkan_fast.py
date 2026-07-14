#!/usr/bin/env python3
import argparse
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


MODEL_PATH = Path("/models/huggingface/staging/unsloth--Qwen3.6-27B-MTP-GGUF/main/Qwen3.6-27B-Q4_K_M.gguf")
MMPROJ_PATH = Path("/models/huggingface/hub/models--unsloth--Qwen3.6-27B-MTP-GGUF/snapshots/5cb35eb3dcbf52dbce5f87dbc64df6aaffadcace/mmproj-BF16.gguf")
SERVER_BINARY = Path("/opt/llama.cpp-vulkan-b9592/build/bin/llama-server")
RUNTIME_LIBRARY_PATH = Path("/opt/llama.cpp-vulkan-b9592/build/bin")
PROFILE_NAME = "gpu45-qwen36-27b-q4km-vulkan-fast"
SERVED_ALIAS = "Qwen3.6-27B-Q4-K-M-Vulkan-Fast"


def require_file(path):
    if not path.is_file():
        raise SystemExit(f"Required file is missing: {path}")


def add_column_if_missing(db, name, definition):
    columns = {row[1] for row in db.execute("PRAGMA table_info(LaunchProfile)")}
    if name not in columns:
        db.execute(f"ALTER TABLE LaunchProfile ADD COLUMN {name} {definition}")


def register(database):
    for path in (MODEL_PATH, MMPROJ_PATH, SERVER_BINARY):
        require_file(path)

    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    model_id = uuid.uuid4().hex
    profile_id = uuid.uuid4().hex
    model_size = MODEL_PATH.stat().st_size

    with sqlite3.connect(database, timeout=30) as db:
        db.execute("PRAGMA journal_mode=WAL")
        add_column_if_missing(db, "backend", "TEXT NOT NULL DEFAULT 'rocm'")
        add_column_if_missing(db, "serverBinary", "TEXT")
        add_column_if_missing(db, "runtimeLibraryPath", "TEXT")
        add_column_if_missing(db, "fanBoostOnBusy", "INTEGER NOT NULL DEFAULT 0")
        db.execute(
            """
            INSERT INTO ModelAsset (
                id, name, path, repo, revision, sizeBytes, multimodal,
                projectorPath, draftPath, active, served, servedAlias,
                defaultModel, createdAt, updatedAt
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL, 0, 1, ?, 0, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                name = excluded.name,
                repo = excluded.repo,
                revision = excluded.revision,
                sizeBytes = excluded.sizeBytes,
                multimodal = 1,
                projectorPath = excluded.projectorPath,
                served = 1,
                servedAlias = excluded.servedAlias,
                updatedAt = excluded.updatedAt
            """,
            (
                model_id,
                MODEL_PATH.name,
                str(MODEL_PATH),
                "unsloth/Qwen3.6-27B-MTP-GGUF",
                "main",
                model_size,
                str(MMPROJ_PATH),
                SERVED_ALIAS,
                now,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO LaunchProfile (
                id, name, description, modelPath, mmprojPath, modelDraftPath,
                host, port, ctxSize, gpuLayers, batchSize, uBatchSize,
                cacheRamMiB, cacheTypeK, cacheTypeV, cacheReuse, specType,
                specDraftNMax, flashAttention, backend, serverBinary,
                runtimeLibraryPath, fanBoostOnBusy, imageMinTokens, metrics,
                jinja, active, createdAt, updatedAt
            ) VALUES (
                ?, ?, ?, ?, ?, NULL, '127.0.0.1', 30000, 262144, 'all', 8192,
                1536, 8192, 'q4_0', 'q4_0', 1024, 'draft-mtp', 2, 'on',
                'vulkan', ?, ?, 1, 1024, 1, 1, 0, ?, ?
            )
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description,
                modelPath = excluded.modelPath,
                mmprojPath = excluded.mmprojPath,
                host = excluded.host,
                port = excluded.port,
                ctxSize = excluded.ctxSize,
                gpuLayers = excluded.gpuLayers,
                batchSize = excluded.batchSize,
                uBatchSize = excluded.uBatchSize,
                cacheRamMiB = excluded.cacheRamMiB,
                cacheTypeK = excluded.cacheTypeK,
                cacheTypeV = excluded.cacheTypeV,
                cacheReuse = excluded.cacheReuse,
                specType = excluded.specType,
                specDraftNMax = excluded.specDraftNMax,
                flashAttention = excluded.flashAttention,
                backend = excluded.backend,
                serverBinary = excluded.serverBinary,
                runtimeLibraryPath = excluded.runtimeLibraryPath,
                fanBoostOnBusy = excluded.fanBoostOnBusy,
                imageMinTokens = excluded.imageMinTokens,
                metrics = excluded.metrics,
                jinja = excluded.jinja,
                updatedAt = excluded.updatedAt
            """,
            (
                profile_id,
                PROFILE_NAME,
                "Verified 256K Vulkan fast profile with embedded MTP2 and load-aware full-fan guard.",
                str(MODEL_PATH),
                str(MMPROJ_PATH),
                str(SERVER_BINARY),
                str(RUNTIME_LIBRARY_PATH),
                now,
                now,
            ),
        )
        db.execute(
            "INSERT INTO AuditLog (id, action, subject, details, createdAt) VALUES (?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex,
                "model.profile.register",
                PROFILE_NAME,
                "Registered the isolated Qwen3.6 Q4_K_M Vulkan fast profile without changing the active model.",
                now,
            ),
        )
        db.commit()

    print(f"Registered {SERVED_ALIAS} in {database}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="prisma/dev.db")
    args = parser.parse_args()
    register(Path(args.database))


if __name__ == "__main__":
    main()
