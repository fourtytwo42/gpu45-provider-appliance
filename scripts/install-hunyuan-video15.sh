#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/gpu45-provider-appliance}"
SOURCE_VENV="${SOURCE_VENV:-/opt/wan2-video-venv}"
VENV_DIR="${HUNYUAN_VENV:-/opt/hunyuan-video-venv}"
MODEL_ROOT="${HUNYUAN_MODEL_ROOT:-/models/hunyuan-video-1.5}"
RUNTIME_ROOT="${HUNYUAN_ROOT:-/opt/hunyuan-video-1.5}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

install -d -o hendo420 -g hendo420 "$MODEL_ROOT" "$RUNTIME_ROOT"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  cp -a --reflink=auto "$SOURCE_VENV" "$VENV_DIR"
  chown -R hendo420:hendo420 "$VENV_DIR"
  sed -i "s#$SOURCE_VENV#$VENV_DIR#g" "$VENV_DIR/pyvenv.cfg" "$VENV_DIR"/bin/activate* || true
fi

# AITER currently rejects gfx1030 and its import hook prevents Diffusers from
# falling back to native SDPA. Keep this isolated from the working WAN venv.
sudo -u hendo420 "$VENV_DIR/bin/python" -m pip uninstall -y flash-attn aiter || true
sudo -u hendo420 "$VENV_DIR/bin/python" -m pip install --upgrade \
  'transformers>=4.57' gguf huggingface_hub

sudo -u hendo420 "$VENV_DIR/bin/python" - <<'PY'
import torch
from diffusers import HunyuanVideo15Pipeline, HunyuanVideo15Transformer3DModel

print(f"torch={torch.__version__} hip={torch.version.hip}")
print(HunyuanVideo15Pipeline.__name__, HunyuanVideo15Transformer3DModel.__name__)
PY

echo "HunyuanVideo 1.5 ROCm environment is importable."
