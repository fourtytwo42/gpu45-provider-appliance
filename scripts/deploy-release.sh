#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
commit="$(git -C "$repo_root" rev-parse HEAD)"
short_commit="${commit:0:12}"
released_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
releases_root="/opt/gpu45/releases"
release_dir="$releases_root/$short_commit"
current_link="/opt/gpu45/current"
data_dir="/var/lib/gpu45"
database_path="$data_dir/appliance.db"
previous_target=""

if [[ "${EUID}" -ne 0 ]]; then
  echo "deploy-release.sh must run as root" >&2
  exit 1
fi

mkdir -p "$releases_root" "$data_dir" /etc/gpu45

if [[ ! -f /etc/gpu45/resource-manager.env ]]; then
  umask 077
  printf 'GPU45_RESOURCE_MANAGER_TOKEN=%s\n' "$(openssl rand -hex 32)" > /etc/gpu45/resource-manager.env
fi
if [[ ! -f /etc/gpu45/backup-password ]]; then
  umask 077
  openssl rand -base64 48 > /etc/gpu45/backup-password
fi
if [[ ! -f /etc/gpu45/backup.env ]]; then
  cat > /etc/gpu45/backup.env <<EOF
RESTIC_PASSWORD_FILE=/etc/gpu45/backup-password
GPU45_BACKUP_REPOSITORY=/models/appliance-backups/restic
GPU45_BACKUP_TARGET=
EOF
  chmod 600 /etc/gpu45/backup.env
fi
if ! command -v restic >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y restic
fi

if [[ ! -f "$database_path" ]]; then
  source_db="$repo_root/prisma/dev.db"
  if [[ ! -f "$source_db" ]]; then
    echo "Missing source database: $source_db" >&2
    exit 1
  fi
  sqlite3 "$source_db" ".backup '$database_path'"
fi

sqlite3 "$database_path" "PRAGMA wal_checkpoint(FULL);"
if [[ "$(sqlite3 "$database_path" "PRAGMA integrity_check;")" != "ok" ]]; then
  echo "Persistent database integrity check failed" >&2
  exit 1
fi

if [[ ! -f /etc/gpu45/appliance.env ]]; then
  if [[ -f "$repo_root/.env.local" ]]; then
    cp "$repo_root/.env.local" /etc/gpu45/appliance.env
  elif [[ -f "$repo_root/.env" ]]; then
    cp "$repo_root/.env" /etc/gpu45/appliance.env
  else
    touch /etc/gpu45/appliance.env
  fi
fi
sed -i '/^DATABASE_URL=/d' /etc/gpu45/appliance.env
printf 'DATABASE_URL=file:%s\n' "$database_path" >> /etc/gpu45/appliance.env
sed -i '/^GPU45_RESOURCE_MANAGER_TOKEN=/d' /etc/gpu45/appliance.env
grep '^GPU45_RESOURCE_MANAGER_TOKEN=' /etc/gpu45/resource-manager.env >> /etc/gpu45/appliance.env
chmod 600 /etc/gpu45/appliance.env

rm -rf "$release_dir"
mkdir -p "$release_dir"
git -C "$repo_root" archive "$commit" | tar -x -C "$release_dir"
cd "$release_dir"
npm ci
DATABASE_URL="file:$database_path" npm run build

cat > /etc/gpu45/release.env <<EOF
GPU45_RELEASE_COMMIT=$commit
GPU45_RELEASED_AT=$released_at
EOF
chmod 644 /etc/gpu45/release.env

install -m 0644 deploy/systemd/gpu45-provider-appliance.service /etc/systemd/system/gpu45-provider-appliance.service
install -m 0644 deploy/systemd/gpu45-provider-appliance-worker.service /etc/systemd/system/gpu45-provider-appliance-worker.service
install -m 0644 deploy/systemd/gpu45-resource-manager.service /etc/systemd/system/gpu45-resource-manager.service
for unit in gpu45-backup.service gpu45-backup.timer gpu45-backup-verify.service gpu45-backup-verify.timer gpu45-restore-drill.service gpu45-restore-drill.timer; do
  install -m 0644 "deploy/systemd/$unit" "/etc/systemd/system/$unit"
done

if [[ -L "$current_link" ]]; then
  previous_target="$(readlink -f "$current_link")"
fi
ln -sfn "$release_dir" "$current_link"
systemctl daemon-reload
systemctl enable --now gpu45-resource-manager.service
systemctl enable --now gpu45-backup.timer gpu45-backup-verify.timer gpu45-restore-drill.timer
systemctl restart gpu45-provider-appliance-worker.service gpu45-provider-appliance.service

healthy=false
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 http://127.0.0.1:3010/api/health/summary >/dev/null; then
    healthy=true
    break
  fi
  sleep 2
done

if [[ "$healthy" != "true" ]]; then
  echo "Release health check failed; rolling back" >&2
  if [[ -n "$previous_target" && -d "$previous_target" ]]; then
    ln -sfn "$previous_target" "$current_link"
    systemctl restart gpu45-provider-appliance-worker.service gpu45-provider-appliance.service
  fi
  exit 1
fi

mapfile -t old_releases < <(find "$releases_root" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +4 | cut -d' ' -f2-)
for old_release in "${old_releases[@]:-}"; do
  [[ -n "$old_release" ]] && rm -rf -- "$old_release"
done

echo "Deployed GPU45 release $short_commit at $released_at"
