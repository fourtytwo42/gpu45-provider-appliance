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

## Final Results

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

Clean, PID-verified comparisons produced:

| Workload | Build 9592 | Build 9992 | Change |
| --- | ---: | ---: | ---: |
| Coding, 1,024 output | 31.86 tok/s | 30.56 tok/s | -4.1% |
| Creative, 1,024 output | 29.50 tok/s | 30.07 tok/s | +1.9% |
| Repository rewrite, 1,024 output | 33.38 tok/s | 33.57 tok/s | +0.6% |
| 12,628-token retrieval, 64 output | 34.38 tok/s | 34.47 tok/s | +0.3% |
| Repository rewrite prompt | 362.99 tok/s | 367.52 tok/s | +1.2% |
| 12,628-token prompt | 356.78 tok/s | 361.22 tok/s | +1.2% |

The new engine does not pass the no-regression gate because coding decode falls by more than 2 percent. Build 9592 remains production.

### Native DFlash

Pinned post-merge draft revision: `5f2ed671305fb1fd8de023d6b335cef4d2663888`.

- Q8 draft SHA-256: `23b6c8ebcc51b3b4107709342fd2960167e88397af36e394923b8d5895ddf7ea`
- Q4 draft SHA-256: `71362369a3428a9e93436a869b1131f63e04b88efbc92dacacb18c419d8de95c`
- Q8 fit in VRAM at about 31.1 GB but decoded at about 7.7 tok/s.
- Q4 decoded at 7.3 to 7.9 tok/s.
- A generation-time stop required SIGKILL before VRAM was released.

DFlash is rejected on this `gfx1030` stack. It is much slower and has worse cancellation behavior than embedded MTP.

The draft assets were moved to recoverable quarantine at `/models/.trash/029b1f6e-6058-4de1-87fa-0edf2e396f1b` with a purge date of 2026-07-20.

### N-gram speculation

- N-gram only: 17.69 tok/s coding and 17.25 tok/s creative.
- MTP plus modified n-gram: 31.85 tok/s coding and 29.85 tok/s creative.
- A 50,428-token stress prompt processed at 303.98 tok/s and decoded at 25.31 tok/s with 81.25 percent draft acceptance.

N-gram only is rejected. The combined profile is effectively tied with production on ordinary prompts and does not justify additional runtime complexity.

### Prompt cache

Build 9592 with prompt caching passed both direct llama.cpp and production Responses API tests.

- First direct 12,628-token request: 37.45 seconds.
- Identical direct request: 2.00 seconds with only four prompt tokens reprocessed.
- Incremental direct follow-up: 6.79 seconds with 1,566 tokens reprocessed.
- Fresh production Responses request, including model startup: 48.14 seconds.
- Production `previous_response_id` follow-up: 2.34 seconds with 12,624 cached tokens.
- Ten of ten forced direct tool calls passed at a 512-token reasoning budget.
- The production Responses tool smoke emitted the correct function call and `response.completed`.
- Three consecutive 2,048-token coding runs held 32.13, 32.20, and 32.21 tok/s.

The active production profile already uses `cacheRamMiB=16384`, `cacheReuse=1024`, and prompt caching. No production profile change is required. llama.cpp reports that cache reuse shifting is disabled for this multimodal model, but exact prefix caching remains effective and is the behavior used by Codex follow-up turns.

## Decision

Keep the current production configuration:

- llama.cpp build 9592.
- Qwen3.6 27B Q5 at 262,144 context.
- Embedded MTP with draft maximum 2 and probability minimum 0.
- Q4 K/V cache and full GPU model residency.
- Prompt caching enabled through the existing 16 GiB ceiling.
- Existing vision projector and Responses proxy.

None of the higher MTP draft settings, upstream engine, DFlash, or n-gram candidates improves the overall production profile. Prompt-prefix reuse is the only large measured latency reduction, and it was already configured correctly.

### Discarded measurements

A root-owned transient evaluation unit ignored normal SIGTERM and remained bound to port 18001. Subsequent launch attempts exited while health checks continued to reach the surviving process. All measurements collected after that failed service transition are excluded from promotion decisions. Clean comparisons require stopping the unit, confirming the port is unbound, and verifying `/proc/<pid>/exe` before every run.

## Gates

- Improve sustained decode without reducing prompt processing by more than 2 percent.
- Preserve 262,144-token context and GPU-only model residency.
- Complete deterministic tool fixtures correctly.
- Preserve Responses streaming and terminal `response.completed` events.
- Complete repeated long outputs without a decode error, driver reset, or second-run degradation.
- Preserve cancellation, VRAM release, and production Q5 restoration.
