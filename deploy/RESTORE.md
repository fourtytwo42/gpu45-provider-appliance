# GPU45 Appliance Restore Notes

This repository contains the appliance management app, local provider launcher/proxy code, service API wrappers, Prisma schema, tests, and restore snapshots for systemd and `/etc/gpu45`.

It intentionally does not contain generated/runtime-heavy artifacts:

- GGUF/model/checkpoint files
- `/models` contents
- generated audio/video/image/transcript outputs
- Next.js build output `.next`
- `node_modules`
- SQLite runtime databases
- Python virtual environments

## Important live paths

- App repo: `/opt/gpu45-provider-appliance`
- Management UI service: `gpu45-provider-appliance.service`
- Collector worker: `gpu45-provider-appliance-worker.service`
- Responses proxy: `gpu45-responses-proxy.service`
- LLM service: `llama-openai.service`
- Image API: `gpu45-image-api.service`
- Whisper API: `gpu45-whisper-api.service`
- TTS API: `qwen3-tts-api.service`
- Video API: `wan2-video-api.service`
- Fan controller: `gpu45-v620-fan-controller.service`
- Provider profile: `/etc/gpu45/provider-profile.json`
- LLM launcher: `/usr/local/bin/gpu45-llm-server`

## Restore outline

1. Install Ubuntu 22.04, ROCm/amdgpu stack, Node.js, npm, Python tooling, build tools, git, and GitHub CLI.
2. Clone this repo to `/opt/gpu45-provider-appliance`.
3. Run `npm ci`, generate Prisma client, initialize the database, and build Next.js.
4. Install service API dependencies and virtual environments for image, Whisper, Qwen3 TTS, and LTX video services.
5. Copy `deploy/systemd/*.service` to `/etc/systemd/system/`.
6. Copy `deploy/etc/gpu45/*` to `/etc/gpu45/` and adjust model paths if models live somewhere different.
7. Copy `deploy/usr/local/bin/gpu45-llm-server` to `/usr/local/bin/gpu45-llm-server` and make it executable.
8. Download model artifacts listed in `docs/model-inventory.md` or the management UI model registry.
9. Run `systemctl daemon-reload`, enable services, and start them.

## Known model profile constraints

- Qwen3.6 27B MTP was the default known-good Codex provider model.
- Gemma 4 12B IT UD-Q8_K_XL works with MTP at 262144 context.
- Gemma 4 26B A4B IT UD-Q8_K_XL works with MTP at 131072 context. Higher contexts caused ROCm OOM or unstable speculative decoding.

## Captured restore assets

- `deploy/systemd/` contains live systemd units.
- `deploy/etc/gpu45/` contains current non-secret GPU45 profile, fan, and tuning JSON.
- `deploy/usr/local/bin/` contains live launcher/proxy executables.
- `deploy/usr/local/sbin/` contains live host tuning and external fan controller scripts.
- `deploy/notes/model-registry.tsv` records current model registry metadata, including model paths and MTP draft files.
- `deploy/notes/launch-profiles.tsv` records per-model launch profile settings from SQLite.

The restore assets are snapshots. After restoring, validate paths against the actual downloaded model locations and then start services.

## External source dependencies

See `deploy/notes/external-source-repos.tsv` for external repositories and exact commit SHAs observed on the live appliance. These are not vendored into this repo because they are upstream projects or experimental stacks.

Core restore should prioritize:

1. `/opt/gpu45-provider-appliance` from this repo.
2. `/opt/qwen3-tts` from the recorded upstream SHA if TTS training/synthesis is needed.
3. `/opt/hunyuan-video-1.5`, `/opt/hunyuan-video-venv`, and `/models/ltx2-eval` if video generation is needed.
4. Recreate Python virtual environments from service dependency requirements or current package imports.

`/models/qwen3-tts` contains runtime voice/model metadata and generated assets. It is intentionally excluded from git; if preserving trained voices matters, back it up separately.

## External local patches

`deploy/patches/` contains `git diff --binary` snapshots and status files for external source directories. Apply these after cloning the matching upstream SHA if those patches are still needed.
