#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR=${GPU45_LLAMA_SOURCE_DIR:-/usr/local/src/rocm-llama.cpp-c58855a895c5d41ac3e01b7432a5971aaf0cabb6}
BUILD_ROOT=${GPU45_VULKAN_BUILD_ROOT:-/opt/llama.cpp-vulkan-b9592}
BUILD_DIR="$BUILD_ROOT/build"
MANIFEST="$BUILD_ROOT/build-manifest.txt"

if [[ ! -f "$SOURCE_DIR/CMakeLists.txt" ]]; then
  echo "llama.cpp source not found: $SOURCE_DIR" >&2
  exit 1
fi
if ! command -v glslc >/dev/null || ! pkg-config --exists vulkan; then
  echo "missing Vulkan build dependencies; install glslc and libvulkan-dev" >&2
  exit 1
fi

mkdir -p "$BUILD_ROOT"
cmake -S "$SOURCE_DIR" -B "$BUILD_DIR" \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_VULKAN=ON \
  -DGGML_NATIVE=ON \
  -DGGML_LTO=OFF \
  -DGGML_BUILD_TESTS=OFF \
  -DGGML_BUILD_EXAMPLES=ON
cmake --build "$BUILD_DIR" --parallel "$(nproc)" --target llama-server llama-bench

{
  echo "source=$SOURCE_DIR"
  echo "source_revision=$(git -C "$SOURCE_DIR" rev-parse HEAD)"
  echo "built_at=$(date --iso-8601=seconds)"
  echo "cmake_build_type=Release"
  echo "ggml_vulkan=ON"
  echo "ggml_native=ON"
  sha256sum "$BUILD_DIR/bin/llama-server" "$BUILD_DIR/bin/llama-bench"
} > "$MANIFEST"

cat "$MANIFEST"
