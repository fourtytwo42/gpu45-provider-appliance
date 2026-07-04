#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/gpu45-provider-appliance}"
WHISPER_ROOT="${WHISPER_ROOT:-/opt/gpu45-whisper-api}"
VENV_DIR="${VENV_DIR:-/opt/gpu45-whisper-venv}"
DATA_DIR="${WHISPER_API_DATA:-/models/whisper}"
PORT="${WHISPER_API_PORT:-8020}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install fastapi "uvicorn[standard]" python-multipart faster-whisper

mkdir -p "$WHISPER_ROOT" "$DATA_DIR"
rsync -a --delete "$APP_ROOT/services/whisper-api/whisper_api/" "$WHISPER_ROOT/whisper_api/"
chown -R hendo420:hendo420 "$WHISPER_ROOT" "$VENV_DIR" "$DATA_DIR"

cat >/etc/systemd/system/gpu45-whisper-api.service <<UNIT
[Unit]
Description=GPU45 Whisper transcription API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=hendo420
Group=hendo420
WorkingDirectory=$WHISPER_ROOT
Environment=WHISPER_API_HOST=0.0.0.0
Environment=WHISPER_API_PORT=$PORT
Environment=WHISPER_API_DATA=$DATA_DIR
Environment=WHISPER_DEVICE=cpu
Environment=WHISPER_COMPUTE_TYPE=int8
ExecStart=$VENV_DIR/bin/python -m whisper_api
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable gpu45-whisper-api.service
systemctl restart gpu45-whisper-api.service
systemctl --no-pager --full status gpu45-whisper-api.service
