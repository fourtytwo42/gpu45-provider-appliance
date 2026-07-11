#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/gpu45-provider-appliance}"
SOURCE_VENV="${SOURCE_VENV:-/opt/wan2-video-venv}"
VENV_DIR="${HUNYUAN_VENV:-/opt/hunyuan-video-venv}"
MODEL_ROOT="${HUNYUAN_MODEL_ROOT:-/models/hunyuan-video-1.5}"
RUNTIME_ROOT="${HUNYUAN_ROOT:-/opt/hunyuan-video-1.5}"
COMFY_ROOT="$RUNTIME_ROOT/ComfyUI"

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

if [[ ! -d "$COMFY_ROOT/.git" ]]; then
  sudo -u hendo420 git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git "$COMFY_ROOT"
fi
if [[ ! -d "$COMFY_ROOT/custom_nodes/ComfyUI-GGUF/.git" ]]; then
  sudo -u hendo420 git clone --depth 1 https://github.com/city96/ComfyUI-GGUF.git "$COMFY_ROOT/custom_nodes/ComfyUI-GGUF"
fi
grep -vE '^(torch|torchvision|torchaudio)([<>= ]|$)' "$COMFY_ROOT/requirements.txt" >/tmp/gpu45-comfy-requirements.txt
sudo -u hendo420 "$VENV_DIR/bin/python" -m pip install -r /tmp/gpu45-comfy-requirements.txt
sudo -u hendo420 "$VENV_DIR/bin/python" -m pip install -r "$COMFY_ROOT/custom_nodes/ComfyUI-GGUF/requirements.txt"

install -d -o hendo420 -g hendo420 "$COMFY_ROOT/models"/{diffusion_models,text_encoders,vae,clip_vision}
ln -sfn "$MODEL_ROOT/480p_distilled/hunyuanvideo1.5_480p_t2v_cfg_distilled-Q5_K_S.gguf" \
  "$COMFY_ROOT/models/diffusion_models/hunyuanvideo1.5_480p_t2v_cfg_distilled-Q5_K_S.gguf"
for kind in text_encoders vae clip_vision; do
  find "$MODEL_ROOT/comfy/split_files/$kind" -maxdepth 1 -type f -exec ln -sfn {} "$COMFY_ROOT/models/$kind/" \; 2>/dev/null || true
done

sudo -u hendo420 "$VENV_DIR/bin/python" - <<'PY'
import torch
from diffusers import HunyuanVideo15Pipeline, HunyuanVideo15Transformer3DModel

print(f"torch={torch.__version__} hip={torch.version.hip}")
print(HunyuanVideo15Pipeline.__name__, HunyuanVideo15Transformer3DModel.__name__)
PY

install -m 0644 "$APP_ROOT/deploy/systemd/hunyuan-video-comfy.service" /etc/systemd/system/hunyuan-video-comfy.service
systemctl daemon-reload
systemctl enable --now hunyuan-video-comfy.service

echo "HunyuanVideo 1.5 ROCm environment is importable."
