#!/usr/bin/env bash
set -euo pipefail

crash_root="/var/crash"
trash_root="/models/.trash"
max_crash_bytes=$((2 * 1024 * 1024 * 1024))

find "$crash_root" -maxdepth 1 -type f -mtime +14 -delete 2>/dev/null || true
current_bytes="$(du -sb "$crash_root" 2>/dev/null | awk '{print $1}' || echo 0)"
while (( current_bytes > max_crash_bytes )); do
  oldest="$(find "$crash_root" -maxdepth 1 -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | head -n 1 | cut -d' ' -f2-)"
  [[ -n "$oldest" ]] || break
  rm -f -- "$oldest"
  current_bytes="$(du -sb "$crash_root" 2>/dev/null | awk '{print $1}' || echo 0)"
done

now_epoch="$(date -u +%s)"
while IFS= read -r -d '' manifest; do
  operation_dir="$(dirname "$manifest")"
  purge_after="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("purgeAfter", ""))' "$manifest" 2>/dev/null || true)"
  [[ -n "$purge_after" ]] || continue
  purge_epoch="$(date -u -d "$purge_after" +%s 2>/dev/null || echo 0)"
  if (( purge_epoch > 0 && purge_epoch <= now_epoch )); then
    rm -rf --one-file-system -- "$operation_dir"
  fi
done < <(find "$trash_root" -mindepth 2 -maxdepth 2 -type f -name manifest.json -print0 2>/dev/null)

mkdir -p /var/lib/gpu45
crash_bytes="$(du -sb "$crash_root" 2>/dev/null | awk '{print $1}' || echo 0)"
trash_bytes="$(du -sb "$trash_root" 2>/dev/null | awk '{print $1}' || echo 0)"
printf '{"updatedAt":"%s","crashBytes":%s,"trashBytes":%s}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$crash_bytes" "$trash_bytes" > /var/lib/gpu45/storage-retention.json
chown gpu45:gpu45 /var/lib/gpu45/storage-retention.json
chmod 0644 /var/lib/gpu45/storage-retention.json
