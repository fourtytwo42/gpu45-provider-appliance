#!/usr/bin/env bash
set -euo pipefail

# Gemma 4 26B A4B Q8 plus its MTP draft does not leave enough VRAM for a
# 256K q4 KV cache and 4K-token prefill graph on the 32 GB V620.
DB="${GPU45_APPLIANCE_DB:-/var/lib/gpu45/appliance.db}"
PROFILE="gpu45-gemma-4-26b-a4b-it-ud-q8-k-xl-044a5cb5"

sqlite3 "$DB" <<SQL
BEGIN IMMEDIATE;
UPDATE LaunchProfile
SET ctxSize = 131072,
    batchSize = 1024,
    uBatchSize = 512,
    description = 'Gemma4 26B A4B Q8 MTP 128k, verified-fit batch/cache for 32GB VRAM',
    updatedAt = datetime('now')
WHERE name = '$PROFILE';
COMMIT;
SQL

count="$(sqlite3 "$DB" "SELECT COUNT(*) FROM LaunchProfile WHERE name='$PROFILE' AND ctxSize=131072 AND batchSize=1024 AND uBatchSize=512;")"
[[ "$count" == "1" ]] || { echo "Gemma 4 26B profile update failed" >&2; exit 1; }
echo "Updated $PROFILE to 128K context, batch 1024, ubatch 512."
