# Wan2.2 TI2V-5B Quality Audit

## Finding

The appliance was not using Wan2.2 TI2V-5B's reference quality path. The model
weights and text encoder are the official full-precision assets, but the service
and UI selected lower-quality inference settings:

- The UI's Quality preset used `832x480` instead of the reference `1280x704`.
- Preview and Balanced used 20 and 30 steps instead of the reference 50 steps.
- The MCP helper used 8 steps.
- Image-to-video inputs were letterboxed onto a black canvas instead of cropped
  to the target aspect ratio.
- The service used a short custom English negative prompt instead of Wan's
  reference negative prompt.
- VAE tiles were smaller than DiffSynth's documented Wan defaults, increasing
  the opportunity for tiled decode inconsistencies.

These differences explain why increasing a web job from 30 to 50 steps helped
but still did not match reference examples: the job remained at the appliance's
non-reference 832x480 resolution and retained the other preprocessing changes.

## Corrected Profiles

| Preset | Resolution | Steps | Duration | Purpose |
| --- | ---: | ---: | ---: | --- |
| Preview | 832x480 | 30 | 2 seconds | Fast composition check |
| Balanced | 1280x704 | 50 | 2 seconds | Reference spatial and sampling quality, shorter clip |
| Quality | 1280x704 | 50 | 5 seconds | Full reference frame count and quality |

The runner now uses CFG 5, shift 5, `30x52` VAE tiles with `15x26` stride, and
aspect-aware center cropping for source images. Portrait output uses the matching
`704x1280` reference orientation.

## Model Limit

This correction removes avoidable appliance-side quality loss. It does not turn
TI2V-5B into the dual-expert A14B model. Complex prompts with several sequential
actions, exact readable text, crowded scenes, or strict multi-subject continuity
can still require multiple seeds or an image-to-video source frame. The appliance
keeps seed control exposed for reproducible comparisons.

## References

- Wan2.2 repository: https://github.com/Wan-Video/Wan2.2
- Wan2.2 TI2V-5B model: https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B
- DiffSynth Wan documentation: https://github.com/modelscope/DiffSynth-Studio/blob/main/docs/en/Model_Details/Wan.md
