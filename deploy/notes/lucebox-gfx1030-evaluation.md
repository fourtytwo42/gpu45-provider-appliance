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

## Model Assets

- Target: `Qwen3.6-27B-Q4_K_M.gguf`, 16,817,244,384 bytes
- Q4 drafter: `dflash-draft-3.6-q4_k_m.gguf`, 1,055,917,280 bytes
- Q8 drafter: `dflash-draft-3.6-q8_0.gguf`, approximately 1.8 GB
- Total evaluation weights: approximately 19 GB

SHA-256:

```text
5ed60d0af4650a854b1755bd392f9aef4872643dc25a254bc68043fa638392a0  Qwen3.6-27B-Q4_K_M.gguf
e2500e90165a0f8e7b52c9882c29ed1fa391c60b300ff11b817bf10e31fa092e  dflash-draft-3.6-q4_k_m.gguf
c6941f629b15107521e4045f309bcf9f29a0035500c96a72e9244492c6abea14  dflash-draft-3.6-q8_0.gguf
```

## Results

| Configuration | Workload | Prompt tok/s | Decode tok/s | Acceptance | Result |
| --- | --- | ---: | ---: | ---: | --- |
| llama.cpp Q4 | Matched baseline | 363.31 | 29.01 | n/a | Pass |
| llama.cpp Q5 | Matched baseline | 356.41 | 29.11 | n/a | Pass |
| Lucebox target only | Short exact response | n/a | 17.1 | n/a | Slower than baseline |
| Q4 DFlash chain | Short coding prompt, 4K context | n/a | 62.8 | 62.5% | Fast favorable case |
| Q4 DFlash chain | Short coding prompt, 256K allocation, three runs | n/a | 69.2-70.1 | 67.2% | Fast favorable case |
| Q4 DFlash DDTree, budget 8 | Short coding prompt | n/a | 48.0-49.7 | 42.1% | Slower than chain |
| Q4 DFlash DDTree, budget 12 | Short coding prompt | n/a | 57.7-59.4 | 52.8% | Slower than chain |
| Q4 DFlash DDTree, budget 16 | Short coding prompt | n/a | 56.2-57.3 | 55.2% | Slower than chain |
| Q4 DFlash DDTree, budget 22 | Short coding prompt | n/a | 56.5-57.7 | 56.6% | Slower than chain |
| Q4 DFlash chain, Q4 KV | 11.8K-13K prompt | 317-318 | 14.5 | 16.4% | Fails prompt and decode gates |
| Q8 DFlash chain, Q4 KV | 13K code prompt | n/a | 0 | 0% | `invalid draft seed -1` |
| Q4 DFlash chain, Q4 KV | 1K-token sustained run 1 | n/a | 0 reported | n/a | Failed after 463 tokens |
| Q4 DFlash chain, Q4 KV | 1K-token sustained run 2 | n/a | 20.6 | 22.4% | Below baseline |
| Q4 DFlash chain, Q4 KV | 1K-token sustained run 3 | n/a | 16.4 | 17.1% | Below baseline |

Full 262,144-token allocation succeeded with both TQ3 and Q4 K/V caches. Q4 K/V used approximately 23.05 GB VRAM. TQ3 used approximately 23.72 GB VRAM. The target and drafter remained on the GPU; there was no CPU model offload.

TQ3 was not safe for production on this build. A real 11,850-token prompt aborted in `ggml-cuda/fattn.cu:312`. The GPU recovered without a driver reset. Q4 K/V avoided that crash but did not meet the performance gates.

The Q8 drafter was not a quality or stability improvement. It reached `invalid draft seed -1` after 243 emitted tokens and returned `decode_failed`.

## Tool and Codex Compatibility

A one-off weather tool fixture initially produced a valid `{"city":"Chicago"}` argument. Ten subsequent deterministic required-tool runs selected the correct function but produced `{"city":""}` every time. Disabling prefix caching did not change the result. The deterministic tool gate therefore scored 0/10.

The long-output test also exposed a server-level failure that would surface in Codex as a disconnected or incomplete response: `invalid draft seed -1` after 462 emitted tokens, followed by `ok=false`, `finish=error`, and `decode_failed`.

Because direct tool correctness and stable completion failed, the Responses proxy, MCP, browser, reconnect, and Desktop-switcher promotion tests were intentionally not performed. Advertising this backend to Codex would make the existing experience less reliable.

## Decision

**Do not promote this Lucebox revision on `gfx1030`.**

The backend is genuinely fast when the prompt is short and the draft model maintains high acceptance. It does not sustain that advantage on long prompts, long outputs, or deterministic tool calls. It fails four mandatory gates:

1. Sustained decode is 16.4-20.6 tok/s instead of the required 35 tok/s and is slower than llama.cpp at 29 tok/s.
2. Long-prompt processing is approximately 317-318 tok/s, more than 2 percent below the 356-363 tok/s llama.cpp baselines.
3. Tool arguments fail deterministically.
4. TQ3 and DFlash each expose fatal or request-ending failure modes.

No Lucebox profile, alias, model-catalog entry, Responses routing, or Desktop Codex setting was added. The production Q4 and Q5 profiles remain unchanged. The production profile was restored and verified as `Qwen3.6-27B-UD-Q5_K_XL-92f1ccba`, with 262,144 context, Q4 K/V cache, MTP, and the vision projector.

The isolated build recipe remains checked in for a future Lucebox revision. Evaluation-only weights are quarantined for normal retention cleanup.
