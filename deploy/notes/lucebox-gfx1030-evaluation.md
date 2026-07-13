# Lucebox DFlash gfx1030 Evaluation

Date: 2026-07-13

## Purpose

Evaluate Lucebox DFlash as an isolated Qwen3.6 27B backend on the Radeon Pro V620 without changing the working llama.cpp Q4 or Q5 profiles.

## Baseline

- GPU: Radeon Pro V620, 32 GB VRAM, `gfx1030`
- ROCm: 7.0.0
- Kernel: Ubuntu 5.15.0-185-generic
- llama.cpp: version 9592, commit `c58855a89`
- Current matched Q4 result: 363.31 prompt tok/s and 29.01 decode tok/s
- Current matched Q5 result: 356.41 prompt tok/s and 29.11 decode tok/s
- Production Responses API: port 30001
- Production backend boundary: `llama-openai.service` on loopback port 30000

The GPU was idle before the build, with no KFD process and approximately 17 MB VRAM in use. The Q4 and Q5 model files and profiles were not modified.

## Pinned Build

- Source: `https://github.com/Luce-Org/lucebox.git`
- Revision: `0e0023649131a23f45d58be71f2bfc60d6cd25a0`
- Block-Sparse-Attention submodule: `49d6c39e4dc0303442cda3bb758b3925d4399c49`
- Source directory: `/opt/lucebox`
- Build directory: `/opt/lucebox/server/build-gfx1030`
- Build dependencies added: `ccache`, `libcurl4-openssl-dev`
- HIP target: `gfx1030`
- rocWMMA flash-prefill: disabled because the optimized path is intended for newer RDNA hardware
- Full KV quant matrix: enabled for Q4 and TQ3 evaluation

The resulting HIP library contains native `amdgcn-amd-amdhsa--gfx1030` code objects. `test_server_unit` completed with 2,053 assertions and zero failures.

## Promotion Gates

- At least 35 decode tok/s on the matched workload
- No more than 2 percent ordinary prompt-processing regression
- Full 262,144-token context without CPU model offload
- Deterministic tool-call fixtures pass
- Long-context and coding quality remain at least 95 percent of the llama.cpp baseline
- Three consecutive long generations complete without driver reset or second-run degradation
- Responses streaming, cancellation, restart, and prior-model restoration work

Until all gates pass, Lucebox remains an isolated experimental build and is not advertised in the model catalog.
