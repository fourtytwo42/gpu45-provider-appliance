# Ornith 1.0 35B Q5 Evaluation

Date: 2026-07-15

## Selected artifact

- Repository: `deepreinforce-ai/Ornith-1.0-35B-GGUF`
- File: `ornith-1.0-35b-Q5_K_M.gguf`
- Size: `24,729,130,848` bytes
- SHA-256: `325b351fc30a4114af5bb21dc2ba7f666ccc90c8f26e6bb36909255d5a449469`
- Served alias: `ornith-1.0-35b-Q5_K_M-688b8d0a`

The publisher has not released an official Ornith 1.0 31B dense GGUF. The 35B
release is a mixture-of-experts model, so the official Q5_K_M artifact was used.

## Runtime profile

- Backend: ROCm llama.cpp
- Context: `262144`
- GPU layers: all
- KV cache: `q4_0` K and V
- Batch / micro-batch: `4096 / 1024`
- Flash attention: enabled
- Speculative decoding: disabled; no compatible MTP companion was published
- Modalities: text only

The loaded process used 27,524,116,480 bytes of the card's 32,195,477,504 bytes
of VRAM. No model layer was offloaded to CPU memory.

## Measured result

The primary run used a 12,628-token uncached long-context prompt and requested
256 output tokens.

| Metric | Result |
| --- | ---: |
| Prompt processing | 1,634.36 tok/s |
| Decode | 63.31 tok/s |
| Total measured duration | 11.864 s |
| Peak VRAM | 27,606,282,240 bytes |
| Peak GPU power | 200 W |
| Peak GPU temperature | 53 C |
| Repeated output lines | 0 |

Two additional 512-token coding runs decoded at 71.76 and 72.06 tok/s. Short
prompt-processing measurements were cache affected and are excluded from the
primary comparison.

For reference, prior appliance history recorded Qwen3.6 27B Q5 at 28.6 decode
tok/s and Qwen3.6 27B Q4 ROCm at 31.8 decode tok/s. These are different models,
so the comparison is useful for appliance throughput rather than model quality.

## Compatibility verification

- Streamed `/v1/responses` ended with `response.completed`.
- Reasoning events were emitted correctly.
- A deterministic function call returned the exact requested JSON arguments.
- `previous_response_id` continuation consumed the tool result and completed.
- Full 256K slot allocation succeeded.
- No amdgpu timeout, reset, page fault, or ROCm error was observed.

## Known limitations

- Text only; the profile has no vision projector.
- No MTP or DFlash companion is configured.
- Model quality and long-context recall require ongoing real Codex use even
  though protocol and tool-call fixtures passed.
