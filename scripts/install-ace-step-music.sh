#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/gpu45-provider-appliance}"
SOURCE_ROOT="${ACE_SOURCE_ROOT:-/opt/ace-step-1.5}"
VENV_ROOT="${ACE_VENV_ROOT:-/opt/ace-step-venv}"
CHECKPOINTS_ROOT="${ACE_CHECKPOINTS_ROOT:-/models/music/ace-step/checkpoints}"
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
requirements="$APP_ROOT/services/music-api/requirements-ace-rocm.txt"
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

ACE_REPO="$(read_manifest aceStep.source)"
ACE_REVISION="$(read_manifest aceStep.revision)"
PYTHON_VERSION="$(read_manifest aceStep.python)"
UV_VERSION="$(read_manifest aceStep.uv)"
TORCH_VERSION="$(read_manifest aceStep.torch)"

install -d -o root -g gpu45-music -m 0755 "$SOURCE_ROOT" "$PYTHON_ROOT"
install -d -o gpu45-music -g gpu45-music -m 0750 "$(dirname "$CHECKPOINTS_ROOT")" "$CHECKPOINTS_ROOT"

install_runtime() {
  if [[ ! -d "$SOURCE_ROOT/.git" ]]; then
    rmdir "$SOURCE_ROOT"
    git clone "$ACE_REPO" "$SOURCE_ROOT"
  fi
  git -C "$SOURCE_ROOT" fetch --tags origin
  git -C "$SOURCE_ROOT" checkout --detach "$ACE_REVISION"
  test "$(git -C "$SOURCE_ROOT" rev-parse HEAD)" = "$ACE_REVISION"

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
    "torch==$TORCH_VERSION" "torchvision==0.24.1+rocm6.4" "torchaudio==$TORCH_VERSION"
  "$VENV_ROOT/bin/python" -m pip install --disable-pip-version-check -r "$requirements"
  "$VENV_ROOT/bin/python" -m pip install --disable-pip-version-check --no-deps -e "$SOURCE_ROOT"

  HSA_OVERRIDE_GFX_VERSION=10.3.0 "$VENV_ROOT/bin/python" - <<'PY'
import torch
assert torch.version.hip, "ROCm PyTorch is required"
assert torch.cuda.is_available(), "V620 is not visible to PyTorch"
print({"torch": torch.__version__, "hip": torch.version.hip, "device": torch.cuda.get_device_name(0)})
PY
  chown -R root:gpu45-music "$SOURCE_ROOT" "$VENV_ROOT" "$PYTHON_ROOT" "$BOOTSTRAP_VENV"
  chmod -R g+rX "$SOURCE_ROOT" "$VENV_ROOT" "$PYTHON_ROOT" "$BOOTSTRAP_VENV"
}

install_models() {
  test -x "$VENV_ROOT/bin/python"
  install -d -o gpu45-music -g gpu45-music -m 0750 "$CHECKPOINTS_ROOT"
  runuser -u gpu45-music -- env \
    HOME=/var/lib/gpu45/music \
    ACESTEP_PROJECT_ROOT="$SOURCE_ROOT" \
    ACESTEP_CHECKPOINTS_DIR="$CHECKPOINTS_ROOT" \
    "$VENV_ROOT/bin/python" - "$manifest" "$CHECKPOINTS_ROOT" <<'PY'
import json
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

manifest_path = Path(sys.argv[1])
checkpoint_root = Path(sys.argv[2])
config = json.loads(manifest_path.read_text(encoding="utf-8"))["aceStep"]
for asset in config["assets"]:
    destination = checkpoint_root if asset["directory"] == "." else checkpoint_root / asset["directory"]
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {asset['repo']}@{asset['revision']} -> {destination}", flush=True)
    snapshot_download(
        repo_id=asset["repo"],
        revision=asset["revision"],
        local_dir=str(destination),
    )
    (destination / ".gpu45-revision").write_text(asset["revision"] + "\n", encoding="utf-8")

from acestep.model_downloader import _sync_model_code_files
for name in ("acestep-v15-xl-base", "acestep-v15-xl-sft", "acestep-v15-xl-turbo"):
    _sync_model_code_files(name, checkpoint_root)
PY

  find "$CHECKPOINTS_ROOT" -type f \
    \( -name '*.safetensors' -o -name '*.bin' -o -name '*.pt' -o -name '*.pth' -o -name '*.json' \) \
    -not -path '*/.cache/*' -print0 \
    | sort -z \
    | xargs -0 sha256sum >"$(dirname "$CHECKPOINTS_ROOT")/SHA256SUMS"
  cp "$manifest" "$(dirname "$CHECKPOINTS_ROOT")/install-manifest.json"
  chown -R gpu45-music:gpu45-music "$(dirname "$CHECKPOINTS_ROOT")"
}

if [[ "$MODE" != "--models-only" ]]; then
  install_runtime
fi
if [[ "$MODE" != "--runtime-only" ]]; then
  install_models
fi

echo "ACE-Step installation complete ($MODE)."
