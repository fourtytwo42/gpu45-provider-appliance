#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR=${LUCEBOX_SOURCE_DIR:-/opt/lucebox}
BUILD_DIR=${LUCEBOX_BUILD_DIR:-$SOURCE_DIR/server/build-gfx1030}
ROCM_PATH=${ROCM_PATH:-/opt/rocm-7.0.0}
LUCEBOX_REVISION=${LUCEBOX_REVISION:-0e0023649131a23f45d58be71f2bfc60d6cd25a0}

if [[ ! -d "$SOURCE_DIR/.git" ]]; then
  echo "Lucebox source is missing at $SOURCE_DIR" >&2
  exit 1
fi

if [[ "$(git -C "$SOURCE_DIR" rev-parse HEAD)" != "$LUCEBOX_REVISION" ]]; then
  echo "Lucebox must be checked out at $LUCEBOX_REVISION" >&2
  exit 1
fi

for command in cmake ninja ccache; do
  command -v "$command" >/dev/null || {
    echo "Missing build dependency: $command" >&2
    exit 1
  }
done

test -x "$ROCM_PATH/llvm/bin/clang++" || {
  echo "ROCm HIP compiler is missing under $ROCM_PATH" >&2
  exit 1
}

cmake -B "$BUILD_DIR" -S "$SOURCE_DIR/server" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DDFLASH27B_GPU_BACKEND=hip \
  -DDFLASH27B_HIP_ARCHITECTURES=gfx1030 \
  -DDFLASH27B_HIP_SM80_EQUIV=OFF \
  -DDFLASH27B_FA_ALL_QUANTS=ON \
  -DROCM_PATH="$ROCM_PATH" \
  -DCMAKE_HIP_COMPILER="$ROCM_PATH/llvm/bin/clang++" \
  -DCMAKE_PREFIX_PATH="$ROCM_PATH"

ninja -C "$BUILD_DIR" dflash_server test_dflash test_server_unit
"$BUILD_DIR/test_server_unit"

echo "Lucebox gfx1030 build completed at $BUILD_DIR"
