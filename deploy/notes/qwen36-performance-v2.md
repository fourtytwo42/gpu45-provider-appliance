# Qwen3.6 27B Performance Evaluation

Date: 2026-07-14

## Result

The promoted profile is `Qwen3.6-27B-Q4-K-M-Vulkan-Fast`.

- Model: Unsloth Qwen3.6 27B MTP `Q4_K_M`
- Backend: pinned llama.cpp b9592 Vulkan build at commit `c58855a89`
- Context: 262,144 tokens with Q4 K/V cache
- Speculation: native MTP, draft count 2
- Vision: BF16 projector enabled and verified through a URL-image Responses request
- Serving boundary: existing port 30000 backend and port 30001 Responses proxy
- Thermal behavior: full fan only while the Vulkan profile is under GPU load, then the normal quiet curve resumes

The production ROCm Q4 and Q5 profiles and binaries were not replaced.

## Comparative Results

| Profile | Prompt tok/s | Decode tok/s | Peak junction | Peak VRAM | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| ROCm UD-Q4_K_XL control, long prompt | 367.83 | 34.80 | 90 C sustained | 28.8 GB | Retained |
| ROCm Q4_K_M, long prompt | 359.29 | 35.95 | Not promoted | About 25.6 GB | Rejected |
| Vulkan Q4_K_M, long prompt, three-run median | 358.39 | 43.65 | 88 C | About 25.6 GB | Promoted |
| Vulkan Q4_K_M OpenSSL rebuild, 512-token coding median | Short prompt | 40.25 | 62 C | 25.5 GB | Verified |

The promoted long-prompt profile improved median decode throughput by about 25.4 percent over the ROCm Q4 control while reducing long-prompt prefill by about 2.6 percent. It also reduced allocated VRAM by roughly 3.2 GB. Three consecutive long runs completed without a driver reset and reached 75 C, 84 C, and 88 C peak junction temperature with load-aware full fan operation.

## Rejected Experiments

- MTP draft counts 4, 6, and 8 with confidence thresholds from 0.50 through 0.85 all reduced end-to-end throughput on this GPU.
- Alternate HIP MMQ and rocBLAS paths did not produce a meaningful gain.
- Text-only ROCm profiles gained less than 5 percent and gave up vision without enough benefit.
- A current upstream Vulkan build did not beat the pinned b9592 Vulkan build.
- The earlier quarantined Q4_K_M file did not contain the required MTP tensors. The promoted profile uses the current MTP-aware GGUF.
- Lucebox, DFlash, NVFP4, PowerPlay replacement, and memory overclock paths did not pass compatibility, performance, or stability gates in their prior isolated evaluations.

## Compatibility Validation

- Streamed `/v1/responses` completed with a terminal `response.completed` event.
- Structured tool calling produced the expected tool name and valid JSON arguments.
- `previous_response_id` and `function_call_output` continuation completed successfully.
- Closing a downstream stream now closes the upstream response and releases the llama.cpp slot.
- The pinned Vulkan build was rebuilt with OpenSSL and correctly interpreted an HTTPS image.
- Intentional two-minute idle unload exits with systemd `Result=success` and clears the fan-boost marker.

## Rollback

Select either existing ROCm alias from the model page or Desktop launcher:

- `Qwen3.6-27B-UD-Q4_K_XL-79071309`
- `Qwen3.6-27B-UD-Q5_K_XL-92f1ccba`

The pre-OpenSSL Vulkan executable is retained as `llama-server.pre-openssl`. The pinned build recipe, launcher selection, fan integration, profile registration, proxy cancellation behavior, and service definitions are tracked in this repository.
