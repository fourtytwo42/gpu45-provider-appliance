# Qwen3.6 Speculative Optimization

Date: 2026-07-13

## Production Rollback Baseline

- Production model: `Qwen3.6-27B-UD-Q5_K_XL-92f1ccba`
- Context: 262,144 tokens
- KV cache: Q4 K/V
- Speculation: embedded MTP, draft maximum 2, probability minimum 0
- Vision: `mmproj-BF16.gguf`
- llama.cpp: build 9592, commit `c58855a89`
- llama-server SHA-256: `48b087e7bffccea2f12784b9c93a33b7e84c783f42fcdc4d67595f276ae752d1`
- Launcher SHA-256: `bde5a712d64d310af54249dfa534a570ccbc761a67e76e4f9154e1507bf64372`
- Profile SHA-256: `d6cabf9df8a4e62203f42ca9a4c51ce9291419421d3ed07918841730df53f02a`
- Rollback snapshot: `/opt/gpu45/rollback/20260713-b9592-q5`

The production binary, launcher, profile, and systemd unit were copied into the rollback snapshot before testing. Experimental servers use a separate port and unit. Existing model files and production runtime paths remain unchanged until a candidate passes all gates.

## Results So Far

### Embedded MTP on production build 9592

All tests used Q5 at 262,144 context with Q4 K/V cache and the vision projector.

| Draft settings | Coding decode | Creative decode | Result |
| --- | ---: | ---: | --- |
| n=2, p=0.00 | 31.89 tok/s | 29.40 tok/s | Production baseline and winner |
| n=4, p=0.50 | 29.28 tok/s | 26.83 tok/s | Reject |
| n=6, p=0.65 | 29.31 tok/s | 24.65 tok/s | Reject |
| n=6, p=0.75 | 26.42 tok/s | 23.97 tok/s | Reject |
| n=8, p=0.75 | 27.51 tok/s | 22.51 tok/s | Reject |
| n=8, p=0.85 | 26.28 tok/s | 21.62 tok/s | Reject |

Additional n=2 and n=3 threshold tests also regressed. The published n=6, p=0.75 result does not transfer to this V620, Q5 quantization, or ROCm build. Keep n=2 and p=0.

### Upstream llama.cpp build 9992

- Revision: `6eddde06a4f25d55d538b5d15628dcc2b6882147`
- Build: isolated HIP `gfx1030` build under `/opt/llama.cpp-upstream/build-gfx1030`
- Production binary and symlink were not changed.
- Same Q5 MTP profile: 30.58 tok/s coding and 30.07 tok/s creative.

The new engine is neutral across these ordinary prompts and does not yet justify replacing build 9592.

### Native DFlash

Pinned post-merge draft revision: `5f2ed671305fb1fd8de023d6b335cef4d2663888`.

- Q8 draft SHA-256: `23b6c8ebcc51b3b4107709342fd2960167e88397af36e394923b8d5895ddf7ea`
- Q4 draft SHA-256: `71362369a3428a9e93436a869b1131f63e04b88efbc92dacacb18c419d8de95c`
- Q8 fit in VRAM at about 31.1 GB but decoded at about 7.7 tok/s.
- Q4 decoded at 7.3 to 7.9 tok/s.
- A generation-time stop required SIGKILL before VRAM was released.

DFlash is rejected on this `gfx1030` stack. It is much slower and has worse cancellation behavior than embedded MTP.

### N-gram speculation

- N-gram only: 17.69 tok/s coding and 17.25 tok/s creative.
- MTP plus modified n-gram: 31.85 tok/s coding and 29.85 tok/s creative.
- A 50,428-token stress prompt processed at 303.98 tok/s and decoded at 25.31 tok/s with 81.25 percent draft acceptance.

N-gram only is rejected. The combined profile is effectively tied with production on ordinary prompts and does not justify additional runtime complexity.

### Discarded measurements

A root-owned transient evaluation unit ignored normal SIGTERM and remained bound to port 18001. Subsequent launch attempts exited while health checks continued to reach the surviving process. All measurements collected after that failed service transition are excluded from promotion decisions. Clean comparisons require stopping the unit, confirming the port is unbound, and verifying `/proc/<pid>/exe` before every run.

## Gates

- Improve sustained decode without reducing prompt processing by more than 2 percent.
- Preserve 262,144-token context and GPU-only model residency.
- Complete deterministic tool fixtures correctly.
- Preserve Responses streaming and terminal `response.completed` events.
- Complete repeated long outputs without a decode error, driver reset, or second-run degradation.
- Preserve cancellation, VRAM release, and production Q5 restoration.
