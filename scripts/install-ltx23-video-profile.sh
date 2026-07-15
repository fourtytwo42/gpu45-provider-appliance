#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/gpu45-provider-appliance}"
COMFY_ROOT="${COMFY_ROOT:-/opt/hunyuan-video-1.5/ComfyUI}"
VENV_ROOT="${VENV_ROOT:-/opt/hunyuan-video-venv}"
MODEL_ROOT="${LTX_MODEL_ROOT:-/models/ltx2-eval}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

test -x "$VENV_ROOT/bin/python"
test -d "$COMFY_ROOT/.git"

install_node() {
  local repo="$1" path="$2" revision="$3"
  if [[ ! -d "$path/.git" ]]; then
    git clone "$repo" "$path"
  fi
  git -C "$path" fetch --tags origin
  git -C "$path" checkout --detach "$revision"
}

install_node https://github.com/city96/ComfyUI-GGUF.git \
  "$COMFY_ROOT/custom_nodes/ComfyUI-GGUF" \
  "${COMFY_GGUF_REVISION:-6ea2651e7df66d7585f6ffee804b20e92fb38b8a}"
install_node https://github.com/Lightricks/ComfyUI-LTXVideo.git \
  "$COMFY_ROOT/custom_nodes/ComfyUI-LTXVideo" \
  "${COMFY_LTX_REVISION:-aceeae9635f6d493f2893ba3c411a1c36031788a}"
install_node https://github.com/pamparamm/comfyui-workflow-to-api-converter-endpoint.git \
  "$COMFY_ROOT/custom_nodes/comfyui-workflow-to-api-converter-endpoint" \
  "${COMFY_API_CONVERTER_REVISION:-bc8538278f82053b3ca10a44d62d02596f8e1a37}"

mkdir -p \
  "$COMFY_ROOT/models/diffusion_models" \
  "$COMFY_ROOT/models/text_encoders" \
  "$COMFY_ROOT/models/vae" \
  "$COMFY_ROOT/models/latent_upscale_models" \
  "$MODEL_ROOT"/{distilled,text_encoders,vae,latent_upscale_models}

declare -A LINKS=(
  ["$MODEL_ROOT/distilled/ltx-2.3-22b-distilled-Q4_K_M.gguf"]="$COMFY_ROOT/models/diffusion_models/ltx-2.3-22b-distilled-Q4_K_M.gguf"
  ["$MODEL_ROOT/text_encoders/gemma-3-12b-it-Q2_K.gguf"]="$COMFY_ROOT/models/text_encoders/gemma-3-12b-it-Q2_K.gguf"
  ["$MODEL_ROOT/text_encoders/ltx-2.3_text_projection_bf16.safetensors"]="$COMFY_ROOT/models/text_encoders/ltx-2.3_text_projection_bf16.safetensors"
  ["$MODEL_ROOT/vae/LTX23_video_vae_bf16.safetensors"]="$COMFY_ROOT/models/vae/LTX23_video_vae_bf16.safetensors"
  ["$MODEL_ROOT/vae/LTX23_audio_vae_bf16.safetensors"]="$COMFY_ROOT/models/vae/LTX23_audio_vae_bf16.safetensors"
  ["$MODEL_ROOT/latent_upscale_models/ltx-2.3-spatial-upscaler-x2-1.1.safetensors"]="$COMFY_ROOT/models/latent_upscale_models/ltx-2.3-spatial-upscaler-x2-1.1.safetensors"
)

for source in "${!LINKS[@]}"; do
  test -s "$source" || { echo "Missing LTX asset: $source" >&2; exit 1; }
  ln -sfn "$source" "${LINKS[$source]}"
done

chown -R hendo420:hendo420 "$MODEL_ROOT" "$COMFY_ROOT/custom_nodes"
rsync -a "$APP_ROOT/services/wan2-video-api/wan_api/" /opt/wan2.2/wan_api/
systemctl restart wan2-video-api.service
systemctl --no-pager --full status wan2-video-api.service
