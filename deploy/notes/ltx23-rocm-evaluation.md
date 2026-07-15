# LTX-2.3 ROCm Evaluation

## Result

LTX-2.3 is viable on the Radeon Pro V620 through ComfyUI, ComfyUI-GGUF, and ROCm. The native CUDA-first Python path is not used. The appliance loads a Q4_K_M distilled transformer, Q2_K Gemma text encoder, BF16 projection and VAEs, and the official 2x latent upscaler without CPU model offload.

## Validated Profiles

| Profile | Input | Output | Steps | Duration | Runtime | Peak VRAM | Peak junction |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Preview | 512x320 | 512x320 | 8 | 1.375s | 147.9s | about 17.9 GB | below 78 C |
| Balanced | 480x272 | 960x512 | 8+3 | 2.042s | 604s | below 32 GB | 78 C |

Both runs produced H.264 video and synchronized 48 kHz stereo AAC audio. The preview showed coherent left-to-right toy-car motion. The balanced run preserved the car across frames and visibly moved it through the scene. After completion, VRAM returned to about 486 MB and the GPU returned to 7 W idle power.

No amdgpu reset, timeout, page fault, RAS, ECC, ROCm illegal-memory-access, or OOM event was observed.

## Production Limits

- Preview exposes text-to-video and image-to-video after both API smoke tests pass.
- Preview duration is exposed from one through five seconds. Five seconds uses 121 frames at 24 fps and is the appliance stress-test target.
- Balanced exposes text-to-video only because that exact workflow passed the hardware gate.
- Retake, keyframes, video-to-video, lip-sync, and audio-to-video remain hidden until each workflow is validated on this card.
- The tiled VAE decode is the largest runtime cost on ROCm. Five-second balanced generation is not a practical default yet.
- The ComfyUI worker is started inside the exclusive video lease and terminated after the job so it cannot overlap the LLM, image, or TTS model allocations.

## Assets

Runtime assets live under `/models/ltx2-eval` and are symlinked into the existing isolated ComfyUI model directories. They are intentionally excluded from Git.
