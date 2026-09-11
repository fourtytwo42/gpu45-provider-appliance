# GPU45 Provider Appliance

Bare-metal management console and OpenAI-compatible inference endpoint for the GPU45 ROCm host.

## Surfaces

- Dashboard: `http://<host>:3010/`
- Responses API: `http://<host>:30001/v1/responses`
- Model catalog: `http://<host>:30001/v1/models`
- llama.cpp backend: loopback port `30000`

The dashboard manages telemetry, fan controls, model downloads, installed model bundles, launch profiles, benchmarks, logs, and API keys. SQLite at `prisma/dev.db` stores management state and history.

## Endpoint Behavior

- Anonymous access is enabled by default and can be disabled on the Keys page.
- Managed keys use `Authorization: Bearer gpu45_...`; only the hash is stored and plaintext is shown once.
- Keys can be named, expired, suspended, resumed, and deleted. Request and token totals are recorded by model.
- `/v1/models` lists only installed primary models explicitly marked as served. MTP and projector artifacts are excluded.
- A supported model name triggers a serialized model switch before inference. Missing or unsupported names use the active model, then the configured fallback model.
- Inference is serialized across model switching so the active model cannot be unloaded during another request.
- `/v1/responses` is normalized to streaming mode and returns SSE headers immediately. The proxy emits keepalive comments while llama.cpp is still processing long full-context prompts, then forwards upstream events when generation starts. This keeps Codex from treating long time-to-first-token prefill as a dead connection.
- Codex `compaction_trigger` requests are handled by the selected GPU45 model. The proxy emits exactly one authenticated, appliance-opaque `compaction` item followed by `response.completed`, then expands that state for the selected model on subsequent turns. Compaction never falls back to a hosted OpenAI model.
- If the configured model is already selected but `llama-openai.service` is stopped, the Responses proxy starts it before inference.

## Model Management

Hugging Face searches and downloads are integrated into the Models page. Compatible MTP artifacts are queued automatically. MTP and projector files are nested under their primary model and can be deleted independently. Deleting a primary model also deletes its attached artifacts. Clearing download history removes queue records only; it never deletes model files.

## Model Tuning Notes

Gemma4-31B Q4 on the V620 is tuned for full `262144` context with `batchSize=2048`, `uBatchSize=1024`, Q4 KV cache, flash attention, and the external MTP draft model enabled. The MTP draft model improves decode throughput, but it does not reduce prompt prefill time. llama.cpp may force full prompt re-processing for Gemma/SWA-style memory instead of reusing prompt cache, so Codex requests with large tool/history payloads can still have noticeable time to first token even when the user-visible prompt is short.

The V620 firmware reports a fixed `250 W` power cap (`power1_cap_min` equals `power1_cap_max`), so the host cannot lower peak wattage through `rocm-smi --setpoweroverdrive`. Lower-power operation is applied through `/etc/gpu45/gpu-tuning.json`; the current safe persistent setting uses `powerProfile` index `2` (`POWER_SAVING`), memory clock level `2` (`673 MHz`), and `vddgfxOffsetMv=-40`. Experimental soft PowerPlay table testing with max GFX lowered from `2571 MHz` to `2100 MHz`, memory restored to `1000 MHz`, and socket power fields set to `225 W` reduced a fixed-load peak from roughly `243-252 W` to about `182 W`, but automatic boot-time soft-table writes are not enabled by default because `pp_table` writes can time out or leave the driver needing a reboot.

## Development

```bash
npm install
npm run lint
npm test
python scripts/test_gpu45_responses_proxy.py
npm run build
```

The production host runs `gpu45-provider-appliance`, `gpu45-provider-appliance-worker`, `gpu45-responses-proxy`, `llama-openai`, and `gpu45-v620-fan-controller` as persistent systemd services.

When deploying proxy changes, copy `scripts/gpu45-responses-proxy.py` to `/usr/local/bin/gpu45-responses-proxy` and restart `gpu45-responses-proxy.service`; the systemd unit runs that installed executable rather than the copy under `/opt/gpu45-provider-appliance`.

## Models

### Qwen3.6 35B A3B Q4 MTP

- Repo: `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`
- Model: `/models/huggingface/staging/unsloth--Qwen3.6-35B-A3B-MTP-GGUF/main/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf`
- Projector: `/models/huggingface/staging/unsloth--Qwen3.6-35B-A3B-MTP-GGUF/main/mmproj-F16.gguf`
- Served alias: `Qwen3.6-35B-A3B-UD-Q4_K_XL-b420e923`
- Context: `262144`
- Quant choice: Q4 XL is the highest practical quant for full 256k context on the 32GB V620. Q5 XL is about 4.3GB larger than Q4 XL while Q4 already uses about 28.1GB of 32.2GB VRAM after loading.
- Runtime defaults: reasoning off, top-k 0, embedded MTP enabled, F16 projector enabled.
