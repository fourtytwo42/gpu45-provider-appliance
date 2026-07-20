#!/usr/bin/env bash
set -euo pipefail

mode="${1:-backup}"
config="/etc/gpu45/backup.env"
status_dir="/var/lib/gpu45/backups"
status_file="$status_dir/status.json"
mkdir -p "$status_dir"
[[ -r "$config" ]] || { echo "Missing $config" >&2; exit 1; }
# shellcheck source=/dev/null
source "$config"
export RESTIC_PASSWORD_FILE
local_repo="${GPU45_BACKUP_REPOSITORY:-/models/appliance-backups/restic}"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

write_status() {
  local state="$1" message="$2" finished_at="${3:-}"
  python3 - "$status_file" "$mode" "$state" "$message" "$started_at" "$finished_at" "$local_repo" "${GPU45_BACKUP_TARGET:-}" <<'PY'
import json, os, sys, tempfile
path, mode, state, message, started, finished, repo, external = sys.argv[1:]
payload = {"operation": mode, "status": state, "message": message, "startedAt": started,
           "finishedAt": finished or None, "repository": repo,
           "externalConfigured": bool(external), "externalTarget": external or None}
os.makedirs(os.path.dirname(path), exist_ok=True)
fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix="status-", suffix=".json")
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2); handle.flush(); os.fsync(handle.fileno())
os.replace(temp, path)
PY
  chown root:gpu45 "$status_file"
  chmod 0640 "$status_file"
}

trap 'code=$?; write_status failed "Backup operation failed with exit code $code" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"; exit $code' ERR
write_status running "Operation in progress"

init_repo() {
  local repo="$1"
  restic -r "$repo" snapshots >/dev/null 2>&1 || restic -r "$repo" init
}

backup_repo() {
  local repo="$1"
  init_repo "$repo"
  local staging=/var/lib/gpu45/backup-staging
  rm -rf "$staging"; mkdir -p "$staging"
  while IFS= read -r -d '' database; do
    name="$(printf '%s' "$database" | sha256sum | cut -c1-12)-$(basename "$database")"
    sqlite3 "$database" ".backup '$staging/$name'"
  done < <(find /var/lib/gpu45 /models/qwen3-tts/api_data -maxdepth 2 -type f -name '*.db' -print0 2>/dev/null)
  local paths=(/var/lib/gpu45 /etc/gpu45 /opt/gpu45-provider-appliance/deploy)
  [[ -d /models/music ]] && paths+=(/models/music)
  [[ -d /models/qwen3-tts/api_data/voices ]] && paths+=(/models/qwen3-tts/api_data/voices)
  while IFS= read -r -d '' metadata; do paths+=("$metadata"); done < <(find /models/qwen3-tts/api_data -maxdepth 1 -type f -name '*.json' -print0 2>/dev/null)
  if [[ -d /models/qwen3-tts/api_data/models ]]; then
    while IFS= read -r -d '' model_dir; do
      while IFS= read -r -d '' model_file; do paths+=("$model_file"); done < <(find "$model_dir" -maxdepth 1 -type f -print0)
      if [[ -d "$model_dir/checkpoint" ]]; then
        while IFS= read -r checkpoint; do [[ -z "$checkpoint" ]] || paths+=("$checkpoint"); done < <(
          find "$model_dir/checkpoint" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -n 2 | cut -d' ' -f2-
        )
      fi
    done < <(find /models/qwen3-tts/api_data/models -mindepth 1 -maxdepth 1 -type d -print0)
  fi
  restic -r "$repo" backup --one-file-system --tag gpu45-appliance \
    --exclude '/var/lib/gpu45/*.db' --exclude '/var/lib/gpu45/*.db-wal' --exclude '/var/lib/gpu45/*.db-shm' \
    --exclude '/models/music/ace-step/checkpoints' --exclude '/models/music/levo2/SongGeneration-v2-large' \
    --exclude '/models/music/jobs/*/outputs' --exclude '/models/music/jobs/*/inputs' \
    "${paths[@]}"
  restic -r "$repo" forget --prune --keep-daily 7 --keep-weekly 4 --keep-monthly 6
}

case "$mode" in
  backup)
    backup_repo "$local_repo"
    [[ -z "${GPU45_BACKUP_TARGET:-}" ]] || backup_repo "$GPU45_BACKUP_TARGET"
    message="Backup completed"
    ;;
  verify)
    init_repo "$local_repo"
    restic -r "$local_repo" check --read-data-subset="${GPU45_BACKUP_VERIFY_SUBSET:-5%}"
    [[ -z "${GPU45_BACKUP_TARGET:-}" ]] || restic -r "$GPU45_BACKUP_TARGET" check
    message="Repository verification completed"
    ;;
  restore-drill)
    init_repo "$local_repo"
    drill_dir="/var/lib/gpu45/restore-drill"
    rm -rf "$drill_dir"; mkdir -p "$drill_dir"
    restic -r "$local_repo" restore latest --target "$drill_dir" --include /var/lib/gpu45
    while IFS= read -r -d '' database; do
      [[ "$(sqlite3 "$database" 'PRAGMA integrity_check;')" == "ok" ]]
    done < <(find "$drill_dir" -type f -name '*.db' -print0)
    rm -rf "$drill_dir"
    message="Restore drill completed"
    ;;
  *) echo "Usage: $0 {backup|verify|restore-drill}" >&2; exit 2 ;;
esac

write_status completed "$message" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
