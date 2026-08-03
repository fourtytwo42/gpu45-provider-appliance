#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/gpu45-provider-appliance}"
WHISPER_ROOT="${WHISPER_ROOT:-/opt/gpu45-whisper-api}"
VENV_DIR="${VENV_DIR:-/opt/gpu45-whisper-rocm-venv}"
ROCM_VENV_DIR="${ROCM_VENV_DIR:-/opt/ace-step-venv}"
DATA_DIR="${WHISPER_API_DATA:-/models/whisper}"
PORT="${WHISPER_API_PORT:-8020}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg

if [[ ! -x "$ROCM_VENV_DIR/bin/python" ]]; then
  echo "ROCm Python environment not found at $ROCM_VENV_DIR" >&2
  exit 1
fi
ROCM_PYTHON="$("$ROCM_VENV_DIR/bin/python" -c 'import sys; print(sys._base_executable)')"
"$ROCM_PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install fastapi "uvicorn[standard]" python-multipart faster-whisper
ROCM_SITE_PACKAGES="$("$ROCM_VENV_DIR/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
VENV_SITE_PACKAGES="$("$VENV_DIR/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
printf '%s\n' "$ROCM_SITE_PACKAGES" >"$VENV_SITE_PACKAGES/gpu45-rocm-runtime.pth"
"$VENV_DIR/bin/python" -m pip install --no-deps openai-whisper
"$VENV_DIR/bin/python" -m pip install more-itertools numba tiktoken tqdm
"$VENV_DIR/bin/python" -c 'import torch, whisper; assert torch.cuda.is_available(), "ROCm GPU is unavailable"; print(torch.__version__, torch.version.hip, torch.cuda.get_device_name(0))'

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
EnvironmentFile=/etc/gpu45/resource-manager.env
Environment=WHISPER_API_HOST=127.0.0.1
Environment=WHISPER_API_PORT=$PORT
Environment=WHISPER_API_DATA=$DATA_DIR
Environment=WHISPER_BACKEND=openai-whisper
Environment=WHISPER_DEVICE=cuda
Environment=WHISPER_COMPUTE_TYPE=float16
Environment=WHISPER_MODEL_DIR=$DATA_DIR/openai-models
Environment=WHISPER_OUTLINE_PROFILE=gpu45-m-shq8-mtp-opta-q5-k-m-69f462b8
Environment=WHISPER_OUTLINE_MODEL=M-SHQ8-MTP-OptA-Q5_K_M-69f462b8
Environment=WHISPER_OUTLINE_LONG_PROFILE=gpu45-qwen3-6-35b-a3b-ud-q4_k_xl-b420e923
Environment=WHISPER_OUTLINE_LONG_MODEL=Qwen3.6-35B-A3B-UD-Q4_K_XL-b420e923
Environment=WHISPER_OUTLINE_BACKEND_URL=http://127.0.0.1:30000
Environment=PYTHONPATH=/opt/gpu45/current/services/common
ExecStart=$VENV_DIR/bin/python -m whisper_api
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl disable gpu45-whisper-api.service || true
systemctl stop gpu45-whisper-api.service || true
systemctl --no-pager --full status gpu45-whisper-api.service || true
