# Video generation upgrade baseline

Captured on 2026-07-10 before the HunyuanVideo 1.5 evaluation.

## Appliance

- Host: `192.168.50.189`
- Kernel: Ubuntu `5.15.0-185-generic`
- GPU target: `gfx1030`, 32 GB VRAM (29.98 GiB visible to PyTorch)
- ROCm userspace: 6.4; amdgpu driver: 6.12.12
- PyTorch: `2.9.1+rocm6.4`
- Filesystem: 936 GiB total, 697 GiB used, 200 GiB free

## Existing video installation

- API unit: `wan2-video-api.service`
- API data: `/models/wan2-video`
- WAN model storage: 166 GiB
- Existing LTX evaluation tree: 97 GiB
- Existing WAN outputs and job metadata are protected during this evaluation.

The live WAN unit sets `GPU_ARCHS=gfx1100` even though the physical target reports
`gfx1030`. That setting is retained for the working WAN backend. Hunyuan uses an
isolated environment without AITER or FlashAttention and starts with PyTorch SDPA.

## Hunyuan evaluation assets

Only selected files are downloaded. The 33.31 GB BF16 transformer is deliberately
excluded because it cannot share a 32 GB card with activations and the required
encoders.

- Pipeline components: `hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v_distilled`
- Transformer: `jayn7/HunyuanVideo-1.5_T2V_480p-GGUF`
- File: `480p_distilled/hunyuanvideo1.5_480p_t2v_cfg_distilled-Q5_K_S.gguf`
- Expected size: 5.94 GB
- Expected SHA-256: `8ce83bc798a62e2e36598238e2ab0c2c32f82815d59b3873ccc87b4f62aab9d4`

The official CFG-distilled T2V model is a 50-step profile. The official 8/12-step
checkpoint is I2V-only, so the UI must not advertise 8/12-step T2V as an equivalent
distilled mode.

