#!/usr/bin/env bash
set -euo pipefail

revision="${LLAMA_CPP_REVISION:-6eddde06a4f25d55d538b5d15628dcc2b6882147}"
source_dir="${LLAMA_CPP_SOURCE_DIR:-/opt/llama.cpp-upstream}"
build_dir="${LLAMA_CPP_BUILD_DIR:-${source_dir}/build-gfx1030}"
rocm_dir="${ROCM_PATH:-/opt/rocm-7.0.0}"

if [[ ! -d "${source_dir}/.git" ]]; then
  git clone https://github.com/ggml-org/llama.cpp.git "${source_dir}"
fi

git -C "${source_dir}" fetch --tags origin "${revision}"
git -C "${source_dir}" checkout --detach "${revision}"

cmake -S "${source_dir}" -B "${build_dir}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_HIP_COMPILER="${rocm_dir}/bin/clang++" \
  -DCMAKE_HIP_ARCHITECTURES=gfx1030 \
  -DGGML_HIP=ON \
  -DGGML_CUDA=OFF \
  -DGGML_NATIVE=OFF \
  -DLLAMA_CURL=ON

cmake --build "${build_dir}" --config Release --parallel "$(nproc)"
"${build_dir}/bin/llama-server" --version
