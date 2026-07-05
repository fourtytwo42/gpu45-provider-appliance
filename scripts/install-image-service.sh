#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/gpu45-provider-appliance}"
IMAGE_ROOT="${IMAGE_ROOT:-/opt/gpu45-image-api}"
VENV_DIR="${VENV_DIR:-/opt/gpu45-image-venv}"
DATA_DIR="${IMAGE_API_DATA:-/models/image-gen}"
PORT="${IMAGE_API_PORT:-8030}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip git

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install --index-url https://download.pytorch.org/whl/rocm6.4 torch torchvision
"$VENV_DIR/bin/python" -m pip install fastapi "uvicorn[standard]" pillow accelerate safetensors transformers sentencepiece protobuf huggingface-hub diffusers

mkdir -p "$IMAGE_ROOT" "$DATA_DIR"
rsync -a --delete "$APP_ROOT/services/image-api/image_api/" "$IMAGE_ROOT/image_api/"
chown -R hendo420:hendo420 "$IMAGE_ROOT" "$VENV_DIR" "$DATA_DIR"

cat >/etc/systemd/system/gpu45-image-api.service <<UNIT
[Unit]
Description=GPU45 image generation API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=hendo420
Group=hendo420
WorkingDirectory=$IMAGE_ROOT
Environment=IMAGE_API_HOST=0.0.0.0
Environment=IMAGE_API_PORT=$PORT
Environment=IMAGE_API_DATA=$DATA_DIR
Environment=IMAGE_MODEL_BASE=$DATA_DIR/models
Environment=IMAGE_DEVICE=cuda
Environment=IMAGE_LLM_SERVICE=llama-openai.service
Environment=IMAGE_GPU_PEER_SERVICES=qwen3-tts-api.service,wan2-video-api.service
Environment=IMAGE_RESTART_LLM=true
Environment=HSA_OVERRIDE_GFX_VERSION=10.3.0
Environment=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
ExecStart=$VENV_DIR/bin/python -m image_api
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/sudoers.d/gpu45-image-api <<SUDOERS
hendo420 ALL=(root) NOPASSWD: /usr/bin/systemctl stop llama-openai.service, /usr/bin/systemctl start llama-openai.service, /usr/bin/systemctl stop qwen3-tts-api.service, /usr/bin/systemctl start qwen3-tts-api.service, /usr/bin/systemctl stop wan2-video-api.service, /usr/bin/systemctl start wan2-video-api.service
SUDOERS
chmod 0440 /etc/sudoers.d/gpu45-image-api

systemctl daemon-reload
systemctl enable gpu45-image-api.service
systemctl restart gpu45-image-api.service
systemctl --no-pager --full status gpu45-image-api.service
