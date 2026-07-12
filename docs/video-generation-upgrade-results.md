# Video generation upgrade results

Validated on the GPU45 `gfx1030` appliance on 2026-07-11.

## Retained production profile

### WAN 2.2 TI2V 5B

- Text-to-video remains available.
- Image-to-video is now available through the same model and API.
- I2V smoke settings: 832x480, 2 seconds, 1 step, seed 123.
- Resource-manager-to-completion time: 143 seconds.
- Generator time: 109 seconds, including 40 seconds for cold pipeline load.
- Denoising: 20.7 seconds.
- Both TTS and the LLM were active again after the lease was released.
- Output preserved the source image composition and produced a valid H.264 MP4.

The one-step smoke test validates the path, not the recommended quality setting.
The UI retains the established 8-step preview default for normal generations.

## Rejected evaluation profiles

### HunyuanVideo 1.5 480p Q5

- The Q5 transformer loaded fully and denoised correctly on ROCm.
- Text encoder allocation: about 8.3 GB.
- Transformer allocation: about 5.7 GB.
- VAE allocation: about 2.4 GB.
- A 320x192, 17-frame, 2-step smoke clip completed in about 159 seconds.
- At 848x480, 21 frames and 20 steps, denoising completed in about 166 seconds.
- ROCm Conv3D VAE decoding then exceeded ten minutes for the two-second clip.

Result: assets retained for seven-day evaluation safety, but the profile is disabled
and reports the failed runtime validation in the UI.

### WAN 2.2 A14B dual expert

- Tested Q4_K_M and Q3_K_M high-noise and low-noise expert pairs.
- The four-step LightX2V workflow loaded and ran the high-noise expert.
- Switching to the low-noise expert exhausted the appliance's 32 GB system RAM.
- Q4 used nearly 5 GB of swap; Q3 still stalled during the expert transition.

Result: the Q3 profile is disabled and reports the RAM/swap validation failure.
The original A14B and evaluation weights remain untouched pending a storage review.

## Quarantine

New evaluation-only Hunyuan and A14B quantized assets were moved to
`/models/.trash/video-upgrade-20260711` after both profiles failed validation.
They are retained for seven days before purge. The pre-existing WAN A14B tree,
production WAN models, job metadata, and generated outputs were not moved.

## Decision

WAN 2.2 TI2V 5B remains the best stable production choice on this specific 32 GB
VRAM plus 32 GB RAM appliance. Hunyuan has a faster transformer but an impractical
ROCm VAE decode on this GPU. A14B needs more system RAM or a backend that can unload
the first expert without retaining enough state to force swap.
