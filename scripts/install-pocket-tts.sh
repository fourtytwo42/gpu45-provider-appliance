#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

python3 -m venv /opt/pocket-tts-venv
chown -R hendo420:hendo420 /opt/pocket-tts-venv
sudo -u hendo420 /opt/pocket-tts-venv/bin/pip install --upgrade pip
sudo -u hendo420 /opt/pocket-tts-venv/bin/pip install --index-url https://download.pytorch.org/whl/cpu torch==2.8.0
sudo -u hendo420 /opt/pocket-tts-venv/bin/pip install pocket-tts==2.1.0 fastapi uvicorn python-multipart

install -d -o hendo420 -g hendo420 /opt/pocket-tts/pocket_tts_api /models/pocket-tts/cache /models/pocket-tts/data
cp -a "$repo_root/services/pocket-tts-api/pocket_tts_api/." /opt/pocket-tts/pocket_tts_api/
install -m 0644 "$repo_root/deploy/systemd/gpu45-pocket-tts-api.service" /etc/systemd/system/gpu45-pocket-tts-api.service
systemctl daemon-reload
systemctl enable --now gpu45-pocket-tts-api.service
