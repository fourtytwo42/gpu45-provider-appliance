#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/gpu45-provider-appliance}"
SOURCE_ROOT="${LEVO_SOURCE_ROOT:-/opt/levo2-amd}"
VENV_ROOT="${LEVO_VENV_ROOT:-/opt/levo2-venv}"
MODEL_ROOT="${LEVO_MODEL_ROOT:-/models/music/levo2}"
BOOTSTRAP_VENV="${GPU45_BOOTSTRAP_VENV:-/opt/gpu45-bootstrap-venv}"
PYTHON_ROOT="${GPU45_PYTHON_ROOT:-/opt/gpu45-python}"
MODE="${1:---all}"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo $0 [--all|--runtime-only|--models-only]" >&2
  exit 1
fi
if [[ "$MODE" != "--all" && "$MODE" != "--runtime-only" && "$MODE" != "--models-only" ]]; then
  echo "Unknown mode: $MODE" >&2
  exit 2
fi

manifest="$APP_ROOT/config/music-models.json"
requirements="$APP_ROOT/services/music-api/requirements-levo-rocm.txt"
test -r "$manifest"
test -r "$requirements"

read_manifest() {
  python3 - "$manifest" "$1" <<'PY'
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
for part in sys.argv[2].split("."):
    value = value[part]
print(value)
PY
}

LEVO_REPO="$(read_manifest levo2.source)"
LEVO_REVISION="$(read_manifest levo2.revision)"
PYTHON_VERSION="$(read_manifest levo2.python)"
UV_VERSION="$(read_manifest levo2.uv)"
TORCH_VERSION="$(read_manifest levo2.torch)"

install -d -o root -g gpu45-music -m 0755 "$PYTHON_ROOT"
install -d -o gpu45-music -g gpu45-music -m 0750 "$MODEL_ROOT" "$MODEL_ROOT/downloads" "$MODEL_ROOT/SongGeneration-v2-large"

install_runtime() {
  if ! command -v git-lfs >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git-lfs
  fi
  if [[ ! -d "$SOURCE_ROOT/.git" ]]; then
    install -d -o root -g gpu45-music -m 0755 "$SOURCE_ROOT"
    git -C "$SOURCE_ROOT" init
    git -C "$SOURCE_ROOT" remote add origin "$LEVO_REPO"
  fi
  git -C "$SOURCE_ROOT" fetch --tags origin
  git -C "$SOURCE_ROOT" checkout --detach "$LEVO_REVISION"
  git -C "$SOURCE_ROOT" lfs pull
  test "$(git -C "$SOURCE_ROOT" rev-parse HEAD)" = "$LEVO_REVISION"
  test "$(stat -c %s "$SOURCE_ROOT/tools/new_auto_prompt.pt")" -gt 1000000

  if [[ ! -x "$BOOTSTRAP_VENV/bin/python" ]]; then
    python3 -m venv "$BOOTSTRAP_VENV"
  fi
  "$BOOTSTRAP_VENV/bin/python" -m pip install --disable-pip-version-check "uv==$UV_VERSION"
  uv="$BOOTSTRAP_VENV/bin/uv"
  export UV_PYTHON_INSTALL_DIR="$PYTHON_ROOT"
  "$uv" python install "$PYTHON_VERSION"

  recreate=false
  if [[ ! -x "$VENV_ROOT/bin/python" ]]; then
    recreate=true
  elif [[ "$($VENV_ROOT/bin/python -c 'import platform; print(platform.python_version())')" != "$PYTHON_VERSION" ]]; then
    recreate=true
  fi
  if [[ "$recreate" == "true" ]]; then
    if [[ -e "$VENV_ROOT" ]]; then
      mv "$VENV_ROOT" "$VENV_ROOT.previous.$(date -u +%Y%m%dT%H%M%SZ)"
    fi
    "$uv" venv --seed --python "$PYTHON_VERSION" "$VENV_ROOT"
  fi

  "$VENV_ROOT/bin/python" -m pip install --disable-pip-version-check \
    --index-url https://download.pytorch.org/whl/rocm6.4 \
    "torch==$TORCH_VERSION" "torchaudio==$TORCH_VERSION"
  "$VENV_ROOT/bin/python" -m pip install --disable-pip-version-check -r "$requirements"

  HSA_OVERRIDE_GFX_VERSION=10.3.0 "$VENV_ROOT/bin/python" - <<'PY'
import torch
assert torch.version.hip, "ROCm PyTorch is required"
assert torch.cuda.is_available(), "V620 is not visible to PyTorch"
print({"torch": torch.__version__, "hip": torch.version.hip, "device": torch.cuda.get_device_name(0)})
PY
  install -d -o gpu45-music -g gpu45-music -m 0750 "$SOURCE_ROOT/out" "$SOURCE_ROOT/gpu45-inputs"
  chown -R root:gpu45-music "$SOURCE_ROOT" "$VENV_ROOT" "$PYTHON_ROOT" "$BOOTSTRAP_VENV"
  chmod -R g+rX "$SOURCE_ROOT" "$VENV_ROOT" "$PYTHON_ROOT" "$BOOTSTRAP_VENV"
  chmod 0770 "$SOURCE_ROOT/out" "$SOURCE_ROOT/gpu45-inputs"
}

install_models() {
  test -x "$VENV_ROOT/bin/python"
  install -d -o gpu45-music -g gpu45-music -m 0750 \
    "$MODEL_ROOT/downloads/runtime" "$MODEL_ROOT/downloads/model" \
    "$MODEL_ROOT/SongGeneration-v2-large/songgeneration" \
    "$MODEL_ROOT/SongGeneration-v2-large/model_1rvq" \
    "$MODEL_ROOT/SongGeneration-v2-large/model_septoken" \
    "$MODEL_ROOT/SongGeneration-v2-large/vae" \
    "$MODEL_ROOT/SongGeneration-v2-large/htdemucs"

  runuser -u gpu45-music -- env HOME=/var/lib/gpu45/music \
    "$VENV_ROOT/bin/python" - "$manifest" "$MODEL_ROOT/downloads" <<'PY'
import json
import sys
from pathlib import Path
from huggingface_hub import hf_hub_download

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["levo2"]
download_root = Path(sys.argv[2])
for asset in manifest["assets"]:
    destination = download_root / asset["group"]
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {asset['repo']}@{asset['revision']}:{asset['file']}", flush=True)
    path = hf_hub_download(
        repo_id=asset["repo"],
        revision=asset["revision"],
        filename=asset["file"],
        local_dir=str(destination),
    )
    target = destination / asset["target"]
    target.parent.mkdir(parents=True, exist_ok=True)
    source = Path(path)
    if source.resolve() != target.resolve():
        source.replace(target)
PY

  runtime="$MODEL_ROOT/downloads/runtime"
  model="$MODEL_ROOT/downloads/model/model_v2_large_orig.pt"
  prepared="$MODEL_ROOT/SongGeneration-v2-large"
  ln -sfn "$runtime/third_party/demucs/ckpt/htdemucs.pth" "$prepared/htdemucs/htdemucs.pth"
  ln -sfn "$runtime/ckpt/vae/autoencoder_music_1320k.ckpt" "$prepared/vae/autoencoder_music_1320k.ckpt"
  ln -sfn "$runtime/ckpt/model_1rvq/model_1rvq.safetensors" "$prepared/model_1rvq/model_1rvq.safetensors"
  ln -sfn "$runtime/ckpt/model_septoken/model_septoken.safetensors" "$prepared/model_septoken/model_septoken.safetensors"
  ln -sfn "$model" "$prepared/songgeneration/model_v2_large_orig.pt"

  if [[ ! -f "$prepared/songgeneration/model_ht_v2_large_fp16_new_data_structure.pt" || ! -f "$prepared/songgeneration/model_st_v2_large_fp16_new_data_structure.pt" ]]; then
    runuser -u gpu45-music -- bash -lc "cd '$prepared/songgeneration' && '$VENV_ROOT/bin/python' '$SOURCE_ROOT/ckpt/songgeneration/convert_fp16.py'"
    runuser -u gpu45-music -- bash -lc "cd '$prepared/songgeneration' && '$VENV_ROOT/bin/python' '$SOURCE_ROOT/ckpt/songgeneration/convert_ckpt_data_structure.py'"
    runuser -u gpu45-music -- bash -lc "cd '$prepared/songgeneration' && '$VENV_ROOT/bin/python' '$SOURCE_ROOT/ckpt/songgeneration/split_ckpt.py'"
    rm -f "$prepared/songgeneration/model_v2_large_fp16.pt" "$prepared/songgeneration/model_v2_large_fp16_new_data_structure.pt"
  fi
  if [[ ! -f "$prepared/model_1rvq/model_1rvq_fp32.safetensors" ]]; then
    runuser -u gpu45-music -- bash -lc "cd '$prepared/model_1rvq' && '$VENV_ROOT/bin/python' '$SOURCE_ROOT/ckpt/model_1rvq/convert_fp32.py'"
  fi
  if [[ ! -f "$prepared/model_septoken/model_septoken_fp32.safetensors" ]]; then
    runuser -u gpu45-music -- bash -lc "cd '$prepared/model_septoken' && '$VENV_ROOT/bin/python' '$SOURCE_ROOT/ckpt/model_septoken/convert_fp32.py'"
  fi

  ln -sfn "$prepared/htdemucs/htdemucs.pth" "$SOURCE_ROOT/ckpt/htdemucs/htdemucs.pth"
  ln -sfn "$prepared/vae/autoencoder_music_1320k.ckpt" "$SOURCE_ROOT/ckpt/vae/autoencoder_music_1320k.ckpt"
  ln -sfn "$prepared/model_1rvq/model_1rvq_fp32.safetensors" "$SOURCE_ROOT/ckpt/model_1rvq/model_1rvq_fp32.safetensors"
  ln -sfn "$prepared/model_septoken/model_septoken_fp32.safetensors" "$SOURCE_ROOT/ckpt/model_septoken/model_septoken_fp32.safetensors"
  ln -sfn "$prepared/songgeneration/model_ht_v2_large_fp16_new_data_structure.pt" "$SOURCE_ROOT/ckpt/songgeneration/model_ht_v2_large_fp16_new_data_structure.pt"
  ln -sfn "$prepared/songgeneration/model_st_v2_large_fp16_new_data_structure.pt" "$SOURCE_ROOT/ckpt/songgeneration/model_st_v2_large_fp16_new_data_structure.pt"

  find "$MODEL_ROOT" -type f \
    \( -name '*.safetensors' -o -name '*.pt' -o -name '*.pth' -o -name '*.ckpt' \) \
    -not -path '*/.cache/*' -print0 | sort -z | xargs -0 sha256sum >"$MODEL_ROOT/SHA256SUMS"
  cp "$manifest" "$MODEL_ROOT/install-manifest.json"
  chown -R gpu45-music:gpu45-music "$MODEL_ROOT"
}

if [[ "$MODE" != "--models-only" ]]; then
  install_runtime
fi
if [[ "$MODE" != "--runtime-only" ]]; then
  install_models
fi

echo "LeVo 2 installation complete ($MODE). Hardware validation is still required."
