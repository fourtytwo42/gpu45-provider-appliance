# WAN Video Retirement

Date: 2026-07-15

WAN 2.1 and WAN 2.2 were retired after LTX-2.3 passed an end-to-end smoke
generation through the appliance API. The live controller was first moved to
`/opt/gpu45-video-api` with a lightweight environment at
`/opt/gpu45-video-api-venv`, so removing the legacy runtime did not affect LTX.

## Removed

- WAN 2.1 T2V 1.3B weights and Hugging Face cache metadata.
- WAN 2.2 TI2V 5B weights.
- WAN 2.2 T2V A14B weights and ComfyUI model links.
- WAN LightX2V LoRA and VAE links.
- `/opt/wan2.2`.
- `/opt/wan2-video-venv`.
- `/opt/DiffSynth-Studio`.
- WAN-specific DiffSynth code, scheduler, tests, installer, and patch files.

Total removed: `196,670,337,805` bytes (about 183.2 GiB).

Filesystem utilization changed from 76% used with 220 GiB free to 56% used
with 403 GiB free.

## Preserved

- LTX-2.3 model assets and ComfyUI runtime.
- Video job database and migration metadata.
- Generated videos, uploads, logs, and LTX Comfy outputs.
- HunyuanVideo files and disabled profile, which are unrelated to WAN.

## Verification

- Lint and TypeScript passed.
- All 19 video-service tests passed.
- Production Next.js build passed.
- LTX Preview generated a one-second 512x320 H.264/AAC video with 25 frames.
- The generated file passed duration and frame-count validation.
- `jobs.db` returned `ok` from `PRAGMA integrity_check` after deletion.
- No retired WAN directory or dangling WAN model link remained.
