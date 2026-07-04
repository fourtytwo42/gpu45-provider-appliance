#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/gpu45-provider-appliance}"
QWEN_ROOT="${QWEN_ROOT:-/opt/qwen3-tts}"
VENV_DIR="${VENV_DIR:-/opt/qwen3-tts-venv}"
DATA_DIR="${QWEN_TTS_API_DATA:-/models/qwen3-tts/api_data}"
PORT="${QWEN_TTS_API_PORT:-8000}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

apt-get update
apt-get install -y git python3 python3-venv python3-pip ffmpeg sox libsox-dev

if [[ ! -d "$QWEN_ROOT/.git" ]]; then
  git clone https://github.com/QwenLM/Qwen3-TTS.git "$QWEN_ROOT"
else
  git -C "$QWEN_ROOT" pull --ff-only
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install --force-reinstall --index-url https://download.pytorch.org/whl/rocm6.4 torch torchaudio
"$VENV_DIR/bin/python" -m pip install -e "$QWEN_ROOT"
"$VENV_DIR/bin/python" -m pip install pypdf python-docx ebooklib beautifulsoup4 lxml mutagen
python3 - <<PY
from pathlib import Path
path = Path("$QWEN_ROOT") / "finetuning" / "sft_12hz.py"
if path.exists():
    content = path.read_text()
    path.write_text(content.replace('attn_implementation="flash_attention_2"', 'attn_implementation="sdpa"'))
PY

rsync -a --delete "$APP_ROOT/services/qwen3-tts-api/tts_api/" "$QWEN_ROOT/tts_api/"
mkdir -p "$DATA_DIR"
chown -R hendo420:hendo420 "$QWEN_ROOT" "$VENV_DIR" "$DATA_DIR"

cat >/etc/systemd/system/qwen3-tts-api.service <<UNIT
[Unit]
Description=Qwen3-TTS API for GPU45 appliance
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=hendo420
Group=hendo420
WorkingDirectory=$QWEN_ROOT
Environment=QWEN_TTS_API_HOST=0.0.0.0
Environment=QWEN_TTS_API_PORT=$PORT
Environment=QWEN_TTS_API_DATA=$DATA_DIR
Environment=QWEN_TTS_DEVICE=cpu
Environment=QWEN_TTS_VRAM_GUARD=true
Environment=QWEN_TTS_EXCLUSIVE_GPU=true
Environment=QWEN_TTS_MIN_FREE_VRAM_MB=8192
Environment=QWEN_TTS_LLM_SERVICE=llama-openai.service
Environment=QWEN_TTS_RESTART_LLM_AFTER=true
Environment=QWEN_TTS_TRAINING_EXCLUSIVE_LLM=true
ExecStart=$VENV_DIR/bin/python -m tts_api
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/sudoers.d/qwen3-tts-vram-guard <<SUDOERS
hendo420 ALL=(root) NOPASSWD: /usr/bin/systemctl stop llama-openai.service, /usr/bin/systemctl start llama-openai.service
SUDOERS
chmod 0440 /etc/sudoers.d/qwen3-tts-vram-guard

systemctl daemon-reload
systemctl enable qwen3-tts-api.service
systemctl restart qwen3-tts-api.service
systemctl --no-pager --full status qwen3-tts-api.service
