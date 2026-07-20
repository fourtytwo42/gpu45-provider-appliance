#!/usr/bin/env bash
set -euo pipefail

cmp -s scripts/gpu45-responses-proxy.py deploy/usr/local/bin/gpu45-responses-proxy || {
  echo "Responses proxy source and release artifact differ" >&2
  exit 1
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
commit="$(git -C "$repo_root" rev-parse HEAD)"
short_commit="${commit:0:12}"
released_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
releases_root="/opt/gpu45/releases"
release_dir="$releases_root/$short_commit"
current_link="/opt/gpu45/current"
slots_root="/opt/gpu45/slots"
shared_root="/opt/gpu45/shared"
data_dir="/var/lib/gpu45"
database_path="$data_dir/appliance.db"
previous_target=""
active_port_file="/var/lib/gpu45/active-web-port"
active_port="3010"
target_port="3011"
caddy_upstream="/etc/caddy/gpu45-upstream.caddy"
dependency_root=""
tts_database_path="/models/qwen3-tts/api_data/jobs.db"

release_healthy() {
  local base_url="$1"
  local host_header="${2:-}"
  local curl_args=(-fsS --max-time 5)
  if [[ -n "$host_header" ]]; then
    curl_args+=(-H "Host: $host_header")
  fi
  curl "${curl_args[@]}" "$base_url/api/health/probe" >/dev/null \
    && curl "${curl_args[@]}" "$base_url/api/version" | grep -q "$commit"
}

if [[ "${EUID}" -ne 0 ]]; then
  echo "deploy-release.sh must run as root" >&2
  exit 1
fi

mkdir -p "$releases_root" "$slots_root" "$shared_root" "$data_dir" /etc/gpu45 /etc/caddy

if [[ ! -f /etc/gpu45/resource-manager.env ]]; then
  umask 077
  printf 'GPU45_RESOURCE_MANAGER_TOKEN=%s\n' "$(openssl rand -hex 32)" > /etc/gpu45/resource-manager.env
fi
if [[ ! -f /etc/gpu45/agentic-benchmark.env ]]; then
  umask 077
  cat > /etc/gpu45/agentic-benchmark.env <<EOF
GPU45_AGENTIC_TOKEN=$(openssl rand -hex 32)
GPU45_AGENTIC_DB=/var/lib/gpu45/benchmarks/agentic.db
GPU45_AGENTIC_ARTIFACT_ROOT=/var/lib/gpu45/benchmarks/artifacts
GPU45_AGENTIC_CACHE_ROOT=/models/benchmark-cache
GPU45_AGENTIC_HOST=127.0.0.1
GPU45_AGENTIC_PORT=8055
GPU45_AGENTIC_MIN_FREE_GB=100
GPU45_APPLIANCE_DB=/var/lib/gpu45/appliance.db
GPU45_RESOURCE_MANAGER_URL=http://127.0.0.1:8040
GPU45_RESPONSES_URL=http://127.0.0.1:30001
GPU45_HARNESS_ROOT=/opt/gpu45/benchmark-harnesses
EOF
  chmod 600 /etc/gpu45/agentic-benchmark.env
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
mkdir -p "$data_dir/migration-backups"
sqlite3 "$database_path" ".backup '$data_dir/migration-backups/appliance-$short_commit.db'"
find "$data_dir/migration-backups" -type f -name 'appliance-*.db' -printf '%T@ %p\n' | sort -nr | tail -n +4 | cut -d' ' -f2- | xargs -r rm -f --
if [[ -f "$tts_database_path" ]]; then
  sqlite3 "$tts_database_path" "PRAGMA wal_checkpoint(FULL);"
  if [[ "$(sqlite3 "$tts_database_path" "PRAGMA integrity_check;")" != "ok" ]]; then
    echo "TTS database integrity check failed" >&2
    exit 1
  fi
  sqlite3 "$tts_database_path" ".backup '${tts_database_path}.migration-$short_commit.bak'"
  find "$(dirname "$tts_database_path")" -maxdepth 1 -type f -name 'jobs.db.migration-*.bak' -printf '%T@ %p\n' | sort -nr | tail -n +4 | cut -d' ' -f2- | xargs -r rm -f --
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
sed -i '/^GPU45_AGENTIC_/d' /etc/gpu45/appliance.env
grep '^GPU45_AGENTIC_TOKEN=' /etc/gpu45/agentic-benchmark.env >> /etc/gpu45/appliance.env
printf 'GPU45_AGENTIC_URL=http://127.0.0.1:8055\n' >> /etc/gpu45/appliance.env
chmod 600 /etc/gpu45/appliance.env

if [[ -f "$active_port_file" ]]; then
  active_port="$(cat "$active_port_file")"
fi
if [[ "$active_port" == "3011" ]]; then
  target_port="3010"
fi

health_json="$(curl -fsS --max-time 10 "http://127.0.0.1:$active_port/api/health/summary" || true)"
if [[ -n "$health_json" ]]; then
  active_jobs="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("jobs",{}).get("active",0))' <<<"$health_json")"
  if (( active_jobs > 0 )); then
    echo "Refusing deployment while $active_jobs job(s) are active" >&2
    exit 1
  fi
fi
source /etc/gpu45/resource-manager.env
resource_json="$(curl -fsS --max-time 5 -H "Authorization: Bearer $GPU45_RESOURCE_MANAGER_TOKEN" http://127.0.0.1:8040/v1/state || true)"
if [[ -n "$resource_json" ]] && ! python3 -c 'import json,sys; state=json.load(sys.stdin); raise SystemExit(0 if state.get("owner") is None and not state.get("queue") else 1)' <<<"$resource_json"; then
  echo "Refusing deployment while the GPU resource manager has active or queued work" >&2
  exit 1
fi

if [[ -L "$current_link" && "$(readlink -f "$current_link")" == "$release_dir" ]]; then
  echo "Release $short_commit is already active; refusing to replace its files" >&2
  exit 1
fi

rm -rf "$release_dir"
mkdir -p "$release_dir"
git -C "$repo_root" archive "$commit" | tar -x -C "$release_dir"

lock_hash="$(sha256sum "$release_dir/package-lock.json" | cut -c1-16)"
dependency_root="$shared_root/$lock_hash"
if [[ ! -x "$dependency_root/node_modules/.bin/next" ]]; then
  mkdir -p "$dependency_root"
  cp "$release_dir/package.json" "$release_dir/package-lock.json" "$dependency_root/"
  npm ci --prefix "$dependency_root"
fi
ln -s "$dependency_root/node_modules" "$release_dir/node_modules"
cd "$release_dir"
DATABASE_URL="file:$database_path" npm run build
DATABASE_URL="file:$database_path" "$dependency_root/node_modules/.bin/tsx" src/scripts/init-db.ts

if [[ ! -f "$data_dir/.telemetry-retention-v2" ]]; then
  systemctl stop gpu45-provider-appliance-worker.service gpu45-provider-appliance.service || true
  if ! bash "$release_dir/scripts/migrate-telemetry-retention.sh" "$database_path"; then
    systemctl start gpu45-provider-appliance-worker.service gpu45-provider-appliance.service || true
    exit 1
  fi
fi

cat > /etc/gpu45/release.env <<EOF
GPU45_RELEASE_COMMIT=$commit
GPU45_RELEASED_AT=$released_at
EOF
chmod 644 /etc/gpu45/release.env

install -m 0644 deploy/systemd/gpu45-provider-appliance@.service /etc/systemd/system/gpu45-provider-appliance@.service
install -m 0644 deploy/systemd/gpu45-provider-appliance-worker.service /etc/systemd/system/gpu45-provider-appliance-worker.service
install -m 0644 deploy/systemd/gpu45-resource-manager.service /etc/systemd/system/gpu45-resource-manager.service
install -m 0644 deploy/systemd/gpu45-agentic-benchmark.service /etc/systemd/system/gpu45-agentic-benchmark.service
install -m 0644 deploy/systemd/gpu45-codex-reference-proxy.service /etc/systemd/system/gpu45-codex-reference-proxy.service
install -m 0644 deploy/systemd/gpu45-tau-simulator.service /etc/systemd/system/gpu45-tau-simulator.service
install -m 0644 deploy/systemd/gpu45-responses-proxy.service /etc/systemd/system/gpu45-responses-proxy.service
install -m 0644 deploy/systemd/llama-openai.service /etc/systemd/system/llama-openai.service
install -m 0644 deploy/systemd/qwen3-tts-api.service /etc/systemd/system/qwen3-tts-api.service
install -m 0644 deploy/systemd/gpu45-pocket-tts-api.service /etc/systemd/system/gpu45-pocket-tts-api.service
install -m 0644 deploy/systemd/gpu45-image-api.service /etc/systemd/system/gpu45-image-api.service
install -m 0644 deploy/systemd/gpu45-whisper-api.service /etc/systemd/system/gpu45-whisper-api.service
install -m 0644 deploy/systemd/wan2-video-api.service /etc/systemd/system/wan2-video-api.service
install -m 0644 deploy/systemd/gpu45-music-api.service /etc/systemd/system/gpu45-music-api.service
install -m 0644 deploy/systemd/hunyuan-video-comfy.service /etc/systemd/system/hunyuan-video-comfy.service
install -m 0755 scripts/configure-service-user.sh /usr/local/sbin/gpu45-configure-service-user
install -m 0755 scripts/install-codex-reference.sh /usr/local/sbin/gpu45-install-codex-reference
/usr/local/sbin/gpu45-configure-service-user
install -m 0755 deploy/usr/local/bin/gpu45-responses-proxy /usr/local/bin/gpu45-responses-proxy
install -m 0755 scripts/gpu45-llm-server /usr/local/bin/gpu45-llm-server
install -m 0755 deploy/usr/local/sbin/gpu45-v620-fan-controller /usr/local/sbin/gpu45-v620-fan-controller
cp -a services/qwen3-tts-api/tts_api/. /opt/qwen3-tts/tts_api/
mkdir -p /opt/pocket-tts/pocket_tts_api
cp -a services/pocket-tts-api/pocket_tts_api/. /opt/pocket-tts/pocket_tts_api/
cp -a services/image-api/image_api/. /opt/gpu45-image-api/image_api/
cp -a services/whisper-api/whisper_api/. /opt/gpu45-whisper-api/whisper_api/
mkdir -p /opt/gpu45-music-api/music_api /var/lib/gpu45/music /models/music /opt/levo2-amd/out /opt/levo2-amd/gpu45-inputs
rm -rf /opt/gpu45-music-api/music_api/*
cp -a services/music-api/music_api/. /opt/gpu45-music-api/music_api/
install -m 0755 services/music-api/music_worker.py /opt/gpu45-music-api/music_worker.py
mkdir -p /opt/gpu45-agentic-benchmark /var/lib/gpu45/benchmarks/artifacts /models/benchmark-cache
rm -rf /opt/gpu45-agentic-benchmark/agentic_benchmark /opt/gpu45-agentic-benchmark/suite-manifests /opt/gpu45-agentic-benchmark/reference-profiles
cp -a services/agentic-benchmark/agentic_benchmark /opt/gpu45-agentic-benchmark/
cp -a services/agentic-benchmark/suite-manifests /opt/gpu45-agentic-benchmark/
cp -a services/agentic-benchmark/reference-profiles /opt/gpu45-agentic-benchmark/
install -m 0644 services/agentic-benchmark/schema.sql /opt/gpu45-agentic-benchmark/schema.sql
install -m 0644 services/agentic-benchmark/harness-lock.json /opt/gpu45-agentic-benchmark/harness-lock.json
chown -R gpu45-benchmark:gpu45-benchmark /opt/gpu45-agentic-benchmark /var/lib/gpu45/benchmarks
if [[ ! -x /opt/gpu45-video-api-venv/bin/python ]]; then
  python3 -m venv /opt/gpu45-video-api-venv
fi
controller_requirements_hash="$(sha256sum services/wan2-video-api/requirements-controller.txt | cut -d' ' -f1)"
if [[ ! -f /opt/gpu45-video-api-venv/.requirements-hash ]] || [[ "$(cat /opt/gpu45-video-api-venv/.requirements-hash)" != "$controller_requirements_hash" ]]; then
  /opt/gpu45-video-api-venv/bin/pip install -r services/wan2-video-api/requirements-controller.txt
  printf '%s\n' "$controller_requirements_hash" > /opt/gpu45-video-api-venv/.requirements-hash
fi
mkdir -p /opt/gpu45-video-api/wan_api
rm -rf /opt/gpu45-video-api/wan_api/*
cp -a services/wan2-video-api/wan_api/. /opt/gpu45-video-api/wan_api/
chown -R hendo420:hendo420 /opt/gpu45-video-api /opt/gpu45-video-api-venv
if [[ ! -x /opt/gpu45-music-api-venv/bin/python ]]; then
  python3 -m venv /opt/gpu45-music-api-venv
fi
music_requirements_hash="$(sha256sum services/music-api/requirements-controller.txt | cut -d' ' -f1)"
if [[ ! -f /opt/gpu45-music-api-venv/.requirements-hash ]] || [[ "$(cat /opt/gpu45-music-api-venv/.requirements-hash)" != "$music_requirements_hash" ]]; then
  /opt/gpu45-music-api-venv/bin/pip install -r services/music-api/requirements-controller.txt
  printf '%s\n' "$music_requirements_hash" > /opt/gpu45-music-api-venv/.requirements-hash
fi
chown -R gpu45-music:gpu45-music /opt/gpu45-music-api /var/lib/gpu45/music /models/music /opt/levo2-amd/out /opt/levo2-amd/gpu45-inputs
for service_db in \
  /models/qwen3-tts/api_data/jobs.db* \
  /models/image-gen/jobs.db* \
  /models/whisper/jobs.db* \
  /models/wan2-video/jobs.db*; do
  [[ -e "$service_db" ]] && chown hendo420:hendo420 "$service_db"
done
install -m 0755 scripts/gpu45-storage-retention.sh /usr/local/sbin/gpu45-storage-retention
for unit in gpu45-backup.service gpu45-backup.timer gpu45-backup-verify.service gpu45-backup-verify.timer gpu45-restore-drill.service gpu45-restore-drill.timer gpu45-storage-retention.service gpu45-storage-retention.timer; do
  install -m 0644 "deploy/systemd/$unit" "/etc/systemd/system/$unit"
done

if [[ -L "$current_link" ]]; then
  previous_target="$(readlink -f "$current_link")"
fi
ln -sfn "$release_dir" "$slots_root/$target_port"

if [[ ! -f "$caddy_upstream" ]]; then
  printf 'reverse_proxy 127.0.0.1:%s\n' "$active_port" > "$caddy_upstream"
fi
install -m 0644 deploy/caddy/Caddyfile /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable gpu45-pocket-tts-api.service
systemctl restart gpu45-pocket-tts-api.service
systemctl enable gpu45-resource-manager.service
systemctl enable gpu45-agentic-benchmark.service
systemctl enable gpu45-codex-reference-proxy.service
systemctl enable gpu45-music-api.service
systemctl restart gpu45-music-api.service
systemctl enable --now gpu45-backup.timer gpu45-backup-verify.timer gpu45-restore-drill.timer gpu45-storage-retention.timer
systemctl enable "gpu45-provider-appliance@$target_port.service"
systemctl restart "gpu45-provider-appliance@$target_port.service"

healthy=false
for _ in $(seq 1 30); do
  if release_healthy "http://127.0.0.1:$target_port"; then
    healthy=true
    break
  fi
  sleep 2
done

if [[ "$healthy" != "true" ]]; then
  echo "Release health check failed before traffic switch" >&2
  systemctl stop "gpu45-provider-appliance@$target_port.service" || true
  exit 1
fi

previous_upstream="$(cat "$caddy_upstream")"
printf 'reverse_proxy 127.0.0.1:%s\n' "$target_port" > "$caddy_upstream.tmp"
mv "$caddy_upstream.tmp" "$caddy_upstream"
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy

if ! release_healthy "http://127.0.0.1" "192-168-50-189.nip.io"; then
  echo "Release failed after traffic switch; restoring previous upstream" >&2
  printf '%s\n' "$previous_upstream" > "$caddy_upstream"
  systemctl reload caddy
  systemctl stop "gpu45-provider-appliance@$target_port.service" || true
  exit 1
fi

ln -sfn "$release_dir" "$current_link"
printf '%s\n' "$target_port" > "$active_port_file"
chmod 0644 "$active_port_file"
systemctl restart gpu45-resource-manager.service gpu45-responses-proxy.service gpu45-provider-appliance-worker.service gpu45-agentic-benchmark.service
if command -v codex >/dev/null 2>&1; then
  systemctl restart gpu45-codex-reference-proxy.service
fi
systemctl try-restart qwen3-tts-api.service gpu45-image-api.service gpu45-whisper-api.service wan2-video-api.service || true
systemctl try-restart gpu45-music-api.service || true

final_healthy=false
for _ in $(seq 1 20); do
  if release_healthy "http://127.0.0.1" "192-168-50-189.nip.io"; then
    final_healthy=true
    break
  fi
  sleep 1
done
if [[ "$final_healthy" != "true" ]]; then
  echo "Release failed after dependent services restarted" >&2
  printf '%s\n' "$previous_upstream" > "$caddy_upstream"
  systemctl reload caddy
  if [[ -n "$previous_target" && -d "$previous_target" ]]; then
    ln -sfn "$previous_target" "$current_link"
  fi
  printf '%s\n' "$active_port" > "$active_port_file"
  systemctl restart gpu45-resource-manager.service gpu45-responses-proxy.service gpu45-provider-appliance-worker.service
  systemctl stop "gpu45-provider-appliance@$target_port.service" || true
  exit 1
fi

systemctl stop gpu45-provider-appliance.service || true
systemctl disable gpu45-provider-appliance.service || true
systemctl reset-failed gpu45-provider-appliance.service || true
if [[ "$active_port" != "$target_port" ]]; then
  systemctl stop "gpu45-provider-appliance@$active_port.service" || true
  systemctl disable "gpu45-provider-appliance@$active_port.service" || true
fi
systemctl disable llama-openai.service || true
systemctl stop llama-openai.service || true
systemctl disable qwen3-tts-api.service gpu45-image-api.service gpu45-whisper-api.service wan2-video-api.service || true

mapfile -t old_releases < <(find "$releases_root" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | tail -n +4 | cut -d' ' -f2-)
for old_release in "${old_releases[@]:-}"; do
  [[ -n "$old_release" ]] && rm -rf -- "$old_release"
done

for dependency_dir in "$shared_root"/*; do
  [[ -d "$dependency_dir" ]] || continue
  if ! find "$releases_root" -maxdepth 2 -type l -name node_modules -lname "$dependency_dir/node_modules" | grep -q .; then
    rm -rf -- "$dependency_dir"
  fi
done

echo "Deployed GPU45 release $short_commit at $released_at"
