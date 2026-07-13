# Qwen3.6 27B NVFP4 Evaluation

Date: 2026-07-13

## Requested Model

- Repository: `unsloth/Qwen3.6-27B-NVFP4`
- Revision evaluated: `ccdaab7e68af2409599b8949a8f2685703c9bae5`
- Format: compressed-tensors mixed precision with NVFP4-packed MLP weights and selected 8-bit weights
- Native context: 262,144 tokens
- MTP: embedded and supported by the recommended vLLM/SGLang launch configuration

## Appliance Hardware and Runtime

- GPU: AMD Radeon Pro V620, 32 GB VRAM
- GPU architecture: `gfx1030` (RDNA2)
- ROCm: 7.0.0
- Kernel: Ubuntu 5.15.0-185-generic
- Current production backend: llama.cpp HIP/ROCm with GGUF models

## Compatibility Result

The NVFP4 checkpoint is not deployable with accelerated GPU-only inference on this appliance.

SGLang's AMD NVFP4 implementation uses Petit. Petit requires AMD CDNA2 or CDNA3 GPUs in the MI2xx and MI3xx families. The V620 is RDNA2 and does not provide the required CDNA MFMA execution path. SGLang's current compatibility matrix likewise limits `petit_nvfp4` to MI250, MI300X, and MI325X.

The model's advertised speed results use NVIDIA Blackwell kernels through vLLM, CuteDSL, CUTLASS, or FlashInfer. Those kernels cannot execute on the V620. llama.cpp does not provide a production-ready HIP NVFP4 path for this Qwen checkpoint. Expanding the checkpoint to BF16 would exceed 32 GB VRAM before allocating the 256K context, vision projector, and runtime buffers. CPU offload was rejected because the appliance requires GPU-only LLM inference.

The checkpoint was therefore not downloaded and was not added to the selectable model catalog. This avoids consuming model storage and avoids advertising an unusable profile.

## Matched Local Benchmark

Both existing models were tested with the same 12,029-token uncached prompt, 256-token output, full 262,144-token launch context, Q4 KV cache, flash attention, and two-token embedded MTP draft configuration. A separate short prompt warmed the execution graph without priming the measured prompt cache.

| Model | Prompt tok/s | Decode tok/s | VRAM after run | Junction temp | Power after run |
| --- | ---: | ---: | ---: | ---: | ---: |
| Qwen3.6 27B UD-Q4_K_XL | 363.31 | 29.01 | 28.75 GB | 58 C | 107 W |
| Qwen3.6 27B UD-Q5_K_XL | 356.41 | 29.11 | 31.04 GB | 60 C | 105 W |

Q4 was 1.94 percent faster for uncached prompt processing. Q5 was 0.35 percent faster for decode, which is within ordinary run variance. Q5 retains the higher-quality weight quantization while fitting the full 256K profile, so it remains the preferred quality default. Q4 remains the lower-VRAM option.

## References

- Unsloth model card: <https://huggingface.co/unsloth/Qwen3.6-27B-NVFP4>
- SGLang AMD GPU documentation: <https://github.com/sgl-project/sglang/blob/main/docs/platforms/amd_gpu.md>
- SGLang quantization compatibility matrix: <https://github.com/sgl-project/sglang/blob/main/docs/advanced_features/quantization.md>
- Petit kernel requirements: <https://github.com/causalflow-ai/petit-kernel>
- llama.cpp NVFP4 implementation discussion: <https://github.com/ggml-org/llama.cpp/discussions/22042>

## Revisit Condition

Re-evaluate this model only if one of the following becomes available:

1. Petit or another ROCm backend adds verified `gfx1030` NVFP4 kernels.
2. llama.cpp adds a correct, accelerated HIP NVFP4 path for Qwen3.6.
3. The appliance GPU is replaced by supported CDNA2/CDNA3 hardware or NVIDIA Blackwell hardware.
