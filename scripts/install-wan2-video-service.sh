#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/gpu45-provider-appliance}"
WAN_ROOT="${WAN_ROOT:-/opt/wan2.2}"
VENV_DIR="${VENV_DIR:-/opt/wan2-video-venv}"
DATA_DIR="${WAN2_API_DATA:-/models/wan2-video}"
FLASH_ATTN_ROOT="${FLASH_ATTN_ROOT:-/opt/flash-attention}"
DIFFSYNTH_ROOT="${DIFFSYNTH_ROOT:-/opt/DiffSynth-Studio}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

apt-get update
apt-get install -y git python3 python3-venv python3-pip ffmpeg

if [[ ! -d "$WAN_ROOT/.git" ]]; then
  git clone https://github.com/Wan-Video/Wan2.2.git "$WAN_ROOT"
else
  git -C "$WAN_ROOT" pull --ff-only
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install --force-reinstall --index-url https://download.pytorch.org/whl/rocm6.4 torch torchvision torchaudio
grep -v -i 'flash' "$WAN_ROOT/requirements.txt" >/tmp/wan2-requirements-no-flash.txt
"$VENV_DIR/bin/python" -m pip install -r /tmp/wan2-requirements-no-flash.txt
"$VENV_DIR/bin/python" -m pip install decord einops librosa peft fastapi 'uvicorn[standard]' huggingface_hub python-multipart

if [[ ! -d "$FLASH_ATTN_ROOT/.git" ]]; then
  git clone https://github.com/Dao-AILab/flash-attention.git "$FLASH_ATTN_ROOT"
else
  git -C "$FLASH_ATTN_ROOT" pull --ff-only
fi

FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE "$VENV_DIR/bin/python" -m pip install --no-build-isolation "$FLASH_ATTN_ROOT"
"$VENV_DIR/bin/python" -m pip uninstall -y triton || true
"$VENV_DIR/bin/python" -m pip install --force-reinstall --index-url https://download.pytorch.org/whl/rocm6.4 pytorch-triton-rocm==3.5.1

if [[ ! -d "$DIFFSYNTH_ROOT/.git" ]]; then
  git clone https://github.com/modelscope/DiffSynth-Studio.git "$DIFFSYNTH_ROOT"
else
  git -C "$DIFFSYNTH_ROOT" pull --ff-only
fi
"$VENV_DIR/bin/python" -m pip install -e "$DIFFSYNTH_ROOT"

rsync -a --delete "$APP_ROOT/services/wan2-video-api/wan_api/" "$WAN_ROOT/wan_api/"
python3 - <<PY
from pathlib import Path

model = Path("$WAN_ROOT/wan/modules/model.py")
model.write_text(model.read_text().replace(
    "from .attention import attention as flash_attention",
    "from .attention import flash_attention",
))

vae = Path("$WAN_ROOT/wan/modules/vae2_2.py")
text = vae.read_text()
text = text.replace(
    'dtype=torch.float,\\n        device="cuda",',
    'dtype=torch.float16,\\n        device="cuda",',
)
text = text.replace(
    ").eval().requires_grad_(False).to(device))",
    ").eval().requires_grad_(False).to(device=device, dtype=dtype))",
)
vae.write_text(text)
PY
mkdir -p "$DATA_DIR"/{outputs,logs}
chown -R hendo420:hendo420 "$WAN_ROOT" "$VENV_DIR" "$DATA_DIR"

cat >/etc/systemd/system/wan2-video-api.service <<UNIT
[Unit]
Description=Wan2.2 video API for GPU45 appliance
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=hendo420
Group=hendo420
WorkingDirectory=$WAN_ROOT
Environment=WAN2_API_HOST=0.0.0.0
Environment=WAN2_API_PORT=8010
Environment=WAN2_ROOT=$WAN_ROOT
Environment=WAN2_PYTHON=$VENV_DIR/bin/python
Environment=WAN2_HF_CLI=$VENV_DIR/bin/huggingface-cli
Environment=WAN2_API_DATA=$DATA_DIR
Environment=WAN2_MODEL_DIR=$DATA_DIR/Wan2.2-TI2V-5B
Environment=WAN2_LLM_SERVICE=llama-openai.service
Environment=WAN2_RESTART_LLM_AFTER=true
Environment=WAN2_VAE_CPU_DECODE=false
Environment=WAN2_OUTPUT_FPS=6
Environment=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
Environment=PYTORCH_ALLOC_CONF=expandable_segments:True
Environment=FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE
Environment=GPU_ARCHS=gfx1100
Environment=AITER_USE_SYSTEM_TRITON=1
Environment=MIOPEN_FIND_MODE=2
Environment=TOKENIZERS_PARALLELISM=false
ExecStart=$VENV_DIR/bin/python -m wan_api
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/sudoers.d/wan2-video-api <<SUDOERS
hendo420 ALL=(root) NOPASSWD: /usr/bin/systemctl stop llama-openai.service, /usr/bin/systemctl start llama-openai.service
SUDOERS
chmod 0440 /etc/sudoers.d/wan2-video-api

systemctl daemon-reload
systemctl enable --now wan2-video-api.service
systemctl --no-pager --full status wan2-video-api.service
