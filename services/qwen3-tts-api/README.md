# GPU45 Qwen3-TTS Service

This service wraps Qwen3-TTS for the GPU45 appliance web console.

It is based on the prior local `Qwen3-TTS/tts_api` implementation and exposes:

- prompt-designed voices from `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`
- voice-cloned trained models from `Qwen/Qwen3-TTS-12Hz-1.7B-Base`
- MP3 synthesis from default, prompt-designed, or trained voices

The appliance webapp proxies this API through `/api/tts`.

## Runtime Placement

The appliance default is CPU TTS:

- `QWEN_TTS_DEVICE=cpu`
- `QWEN_TTS_VRAM_GUARD=false`

This keeps the LLM resident on the GPU and avoids stopping/restarting llama.cpp for normal TTS work. Benchmarks on 2026-07-02 showed CPU TTS was comparable to the current ROCm GPU path for short clips while using essentially no additional VRAM.

## VRAM Guard

Qwen3-TTS is smaller than the active LLM models, but the service can still unload the LLM provider before TTS work if free VRAM is below a configured threshold.

Environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `QWEN_TTS_VRAM_GUARD` | `true` | Enable host VRAM check before model load/generation/training. |
| `QWEN_TTS_EXCLUSIVE_GPU` | `true` | Stop the LLM for the full duration of GPU TTS work instead of only when free VRAM is low. |
| `QWEN_TTS_MIN_FREE_VRAM_MB` | `8192` | Minimum free VRAM desired before TTS work. |
| `QWEN_TTS_LLM_SERVICE` | `llama-openai.service` | LLM systemd service to stop when VRAM is tight. |
| `QWEN_TTS_RESTART_LLM_AFTER` | `false` | Restart the LLM after the TTS job if the guard stopped it. |
| `QWEN_TTS_GPU_CARD_GLOB` | `/sys/class/drm/card*/device` | GPU sysfs card glob used for VRAM readings. |

## Install

Use `scripts/install-qwen3-tts-service.sh` from this repo on the appliance host.
