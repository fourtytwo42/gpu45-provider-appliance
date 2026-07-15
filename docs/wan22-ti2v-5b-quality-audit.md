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
- VAE tiles were smaller than DiffSynth's documented Wan defaults. A hardware
  comparison showed the larger reference tiles are not practical on gfx1030:
  one of six decode tiles took 222 seconds for a two-second 720p smoke clip.

These differences explain why increasing a web job from 30 to 50 steps helped
but still did not match reference examples: the job remained at the appliance's
non-reference 832x480 resolution and retained the other preprocessing changes.

## Corrected Profiles

| Preset | Resolution | Steps | Duration | Purpose |
| --- | ---: | ---: | ---: | --- |
| Preview | 832x480 | 30 | 2 seconds | Fast composition check |
| Balanced | 1280x704 | 50 | 2 seconds | Reference spatial and sampling quality, shorter clip |
| Quality | 1280x704 | 50 | 5 seconds | Full reference frame count and quality |

The runner now uses CFG 5, shift 5, aspect-aware center cropping for source
images, and the full reference output resolution. It retains `24x40` VAE tiles
with `12x20` stride as a documented V620-specific performance concession; this
changes decode tiling, not the generated frame resolution. Portrait output uses
the matching `704x1280` reference orientation.

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

## Scheduler Evaluation

The official Wan runner uses Flow UniPC, while DiffSynth defaults to a first-order
flow Euler scheduler. A compatibility adapter completed a 1280x704, 49-frame,
four-step I2V hardware test in 615 seconds. It produced visible prompted motion,
completed all nine VAE decode tiles, and wrote a valid 2.04-second MP4 without a
driver error. New TI2V-5B jobs therefore use UniPC; Euler remains available as an
internal rollback.

The official runner also offers optional local-Qwen prompt extension. The
appliance does not silently rewrite user prompts in this release. I2V prompts
should describe motion and transitions that are plausible from the supplied
source image; unrelated scene replacement remains unreliable on the 5B model.

## Hardware Results

- Reference-memory smoke: 1280x704, 49 frames, one Euler step completed in 397
  seconds. The output was 2.042 seconds long with all 49 frames present.
- Production-path validation: job `736c067a-e684-421e-9345-1472520ea4ed`
  completed 50 Euler steps and all nine VAE tiles at 1280x704. Denoising took 60
  minutes 43 seconds. The resulting MP4 is 2.042 seconds and 49 frames.
- The production-path source frame was preserved more cleanly than the earlier
  832x480 output, but its test prompt requested unrelated objects absent from the
  source and produced little motion. This confirms that resolution alone does
  not repair an implausible I2V transition.
- UniPC validation: 1280x704, 49 frames, four steps completed in 615 seconds.
  The output visibly introduced the prompted foreground motion and completed
  without a ROCm or driver fault. Four steps were visibly under-resolved and are
  not exposed as a user preset.
- Full UniPC production validation: job
  `1c2dee91-2dd9-4ffa-a167-b1fd79175027` completed 50 steps and all nine VAE
  decode tiles at 1280x704 in 66 minutes 11 seconds. The resulting H.264 MP4 is
  2.042 seconds and 49 frames. The theater source remained sharp and stable,
  and the prompted foreground object appeared and moved consistently. The 5B
  model interpreted the requested twenty-sided die as a wheel-like object, so
  strict geometry and identity adherence remain model limitations rather than
  pipeline failures.
- Live progress correctly transitioned from denoising to `Decoding frame tiles
  X/9` at 90-98 percent instead of appearing to restart denoising.
- Peak observed junction temperature was 92 C during VAE decode. The fan curve
  brought the card back down between tiles. GPU utilization and VRAM returned to
  zero after each run, and kernel logs contained no GPU reset, timeout, or page
  fault.
