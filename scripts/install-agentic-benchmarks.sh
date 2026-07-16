#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
service_root="/opt/gpu45-agentic-benchmark"
harness_root="/opt/gpu45/benchmark-harnesses"
cache_root="/models/benchmark-cache"
state_root="/var/lib/gpu45/benchmarks"
lock_file="$repo_root/services/agentic-benchmark/harness-lock.json"

if [[ "$EUID" -ne 0 ]]; then
  echo "install-agentic-benchmarks.sh must run as root" >&2
  exit 1
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io git curl ca-certificates sqlite3 jq acl

getent group docker >/dev/null || groupadd --system docker
if ! id gpu45-benchmark >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/gpu45-benchmark --shell /usr/sbin/nologin gpu45-benchmark
fi
usermod -aG docker gpu45-benchmark

install -d -o gpu45-benchmark -g gpu45-benchmark -m 0750 "$service_root" "$harness_root" "$state_root" "$state_root/artifacts"
install -d -o root -g docker -m 0770 "$cache_root" "$cache_root/docker"
setfacl -m u:gpu45-benchmark:--x /var/lib/gpu45
rm -rf "$service_root/agentic_benchmark" "$service_root/suite-manifests"
cp -a "$repo_root/services/agentic-benchmark/agentic_benchmark" "$service_root/"
cp -a "$repo_root/services/agentic-benchmark/suite-manifests" "$service_root/"
install -m 0644 "$repo_root/services/agentic-benchmark/schema.sql" "$service_root/schema.sql"
install -m 0644 "$lock_file" "$service_root/harness-lock.json"
chown -R gpu45-benchmark:gpu45-benchmark "$service_root" "$harness_root" "$state_root"

install -d -m 0755 /etc/docker
python3 - <<'PY'
import json
from pathlib import Path

path = Path('/etc/docker/daemon.json')
try:
    data = json.loads(path.read_text()) if path.exists() else {}
except json.JSONDecodeError as exc:
    raise SystemExit(f"Refusing to overwrite invalid {path}: {exc}")
data.update({
    'data-root': '/models/benchmark-cache/docker',
    'userland-proxy': False,
    'log-driver': 'local',
    'log-opts': {'max-size': '20m', 'max-file': '3'},
})
path.write_text(json.dumps(data, indent=2) + '\n')
PY

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
UV_CACHE_DIR=/models/benchmark-cache/uv
EOF
  chmod 0600 /etc/gpu45/agentic-benchmark.env
fi
grep -q '^UV_CACHE_DIR=' /etc/gpu45/agentic-benchmark.env || echo 'UV_CACHE_DIR=/models/benchmark-cache/uv' >> /etc/gpu45/agentic-benchmark.env

uv_version="$(jq -r '.uv' "$lock_file")"
uv_bin="$harness_root/bin/uv"
if [[ ! -x "$uv_bin" ]] || [[ "$($uv_bin --version 2>/dev/null | awk '{print $2}')" != "$uv_version" ]]; then
  install -d -o gpu45-benchmark -g gpu45-benchmark -m 0755 "$harness_root/bin"
  curl -LsSf "https://astral.sh/uv/${uv_version}/install.sh" | env UV_INSTALL_DIR="$harness_root/bin" INSTALLER_NO_MODIFY_PATH=1 sh
  chown -R gpu45-benchmark:gpu45-benchmark "$harness_root/bin"
fi

runuser -u gpu45-benchmark -- python3 - "$lock_file" "$harness_root" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

lock = json.loads(Path(sys.argv[1]).read_text())
root = Path(sys.argv[2]) / 'sources'
root.mkdir(parents=True, exist_ok=True)
for name, source in lock['repositories'].items():
    target = root / name
    if not (target / '.git').exists():
        subprocess.run(['git', 'clone', '--filter=blob:none', '--no-checkout', source['url'], str(target)], check=True)
    subprocess.run(['git', '-C', str(target), 'fetch', '--depth', '1', 'origin', source['commit']], check=True)
    subprocess.run(['git', '-C', str(target), 'checkout', '--detach', source['commit']], check=True)
PY
chown -R gpu45-benchmark:gpu45-benchmark "$harness_root"

install -d -o gpu45-benchmark -g gpu45-benchmark -m 0770 "$cache_root/uv" "$harness_root/venvs"
[[ -x "$harness_root/venvs/bfcl/bin/python" ]] || runuser -u gpu45-benchmark -- env HOME=/var/lib/gpu45-benchmark XDG_CONFIG_HOME=/var/lib/gpu45-benchmark/.config UV_NO_CONFIG=1 UV_CACHE_DIR="$cache_root/uv" "$uv_bin" venv --python 3.12 "$harness_root/venvs/bfcl"
runuser -u gpu45-benchmark -- env HOME=/var/lib/gpu45-benchmark XDG_CONFIG_HOME=/var/lib/gpu45-benchmark/.config UV_NO_CONFIG=1 UV_CACHE_DIR="$cache_root/uv" "$uv_bin" pip install --python "$harness_root/venvs/bfcl/bin/python" -e "$harness_root/sources/bfcl/berkeley-function-call-leaderboard" soundfile==0.13.1
runuser -u gpu45-benchmark -- env HOME=/var/lib/gpu45-benchmark XDG_CONFIG_HOME=/var/lib/gpu45-benchmark/.config UV_NO_CONFIG=1 UV_CACHE_DIR="$cache_root/uv" UV_PROJECT_ENVIRONMENT="$harness_root/venvs/tau" "$uv_bin" sync --frozen --python 3.13 --project "$harness_root/sources/tau"
[[ -x "$harness_root/venvs/swebench/bin/python" ]] || runuser -u gpu45-benchmark -- env HOME=/var/lib/gpu45-benchmark XDG_CONFIG_HOME=/var/lib/gpu45-benchmark/.config UV_NO_CONFIG=1 UV_CACHE_DIR="$cache_root/uv" "$uv_bin" venv --python 3.12 "$harness_root/venvs/swebench"
runuser -u gpu45-benchmark -- env HOME=/var/lib/gpu45-benchmark XDG_CONFIG_HOME=/var/lib/gpu45-benchmark/.config UV_NO_CONFIG=1 UV_CACHE_DIR="$cache_root/uv" "$uv_bin" pip install --python "$harness_root/venvs/swebench/bin/python" -e "$harness_root/sources/swebench"
[[ -x "$harness_root/venvs/mini-swe-agent/bin/python" ]] || runuser -u gpu45-benchmark -- env HOME=/var/lib/gpu45-benchmark XDG_CONFIG_HOME=/var/lib/gpu45-benchmark/.config UV_NO_CONFIG=1 UV_CACHE_DIR="$cache_root/uv" "$uv_bin" venv --python 3.12 "$harness_root/venvs/mini-swe-agent"
runuser -u gpu45-benchmark -- env HOME=/var/lib/gpu45-benchmark XDG_CONFIG_HOME=/var/lib/gpu45-benchmark/.config UV_NO_CONFIG=1 UV_CACHE_DIR="$cache_root/uv" "$uv_bin" pip install --python "$harness_root/venvs/mini-swe-agent/bin/python" -e "$harness_root/sources/miniSweAgent"
runuser -u gpu45-benchmark -- env HOME=/var/lib/gpu45-benchmark XDG_CONFIG_HOME=/var/lib/gpu45-benchmark/.config UV_NO_CONFIG=1 UV_CACHE_DIR="$cache_root/uv" UV_PROJECT_ENVIRONMENT="$harness_root/venvs/harbor" "$uv_bin" sync --frozen --python 3.12 --project "$harness_root/sources/harbor"

"$harness_root/venvs/bfcl/bin/bfcl" --help >/dev/null
"$harness_root/venvs/tau/bin/python" -c 'import tau2'
"$harness_root/venvs/swebench/bin/python" -c 'import swebench'
"$harness_root/venvs/mini-swe-agent/bin/mini" --help >/dev/null
"$harness_root/venvs/harbor/bin/harbor" --help >/dev/null

install -m 0644 "$repo_root/deploy/systemd/gpu45-agentic-benchmark.service" /etc/systemd/system/gpu45-agentic-benchmark.service
systemctl daemon-reload
systemctl enable docker.service gpu45-agentic-benchmark.service
systemctl restart docker.service
systemctl restart gpu45-agentic-benchmark.service

docker info >/dev/null
[[ "$(docker info --format '{{.DockerRootDir}}')" == "$cache_root/docker" ]]
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m alpine:3.22 sh -c 'test ! -e /dev/dri && echo sandbox-ok'

source /etc/gpu45/agentic-benchmark.env
curl -fsS http://127.0.0.1:8055/health | jq -e '.status == "ready"' >/dev/null
echo "GPU45 agentic benchmark runtime installed"
