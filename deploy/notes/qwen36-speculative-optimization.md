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

## Gates

- Improve sustained decode without reducing prompt processing by more than 2 percent.
- Preserve 262,144-token context and GPU-only model residency.
- Complete deterministic tool fixtures correctly.
- Preserve Responses streaming and terminal `response.completed` events.
- Complete repeated long outputs without a decode error, driver reset, or second-run degradation.
- Preserve cancellation, VRAM release, and production Q5 restoration.
