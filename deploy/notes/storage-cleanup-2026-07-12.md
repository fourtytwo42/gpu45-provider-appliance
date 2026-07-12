# Storage cleanup evidence - 2026-07-12

- `/models/.trash/image-quality-upgrade-20260710`: 98 GB of retired `sdxl-turbo`, `sd-turbo`, `qwen-image-gguf-q3`, and `ssd-1b` assets. No service, profile, job, runtime import, or symlink referenced these paths.
- `/var/crash/_usr_bin_python3.10.1000.crash`: 12,917,024,478 bytes, written 2026-07-06 01:33 UTC. Apport metadata identifies `/opt/gpu45-image-venv/bin/python -m image_api` on Ubuntu 22.04, kernel 5.15.0-185.
- Resource manager had no owner or queued lease. All model workers were idle and the GPU used about 17 MB VRAM before cleanup.
- Restic snapshot `70451e06` completed before cleanup.
- Both paths were approved for permanent removal after reference validation. Future crash data is capped at 2 GB; recoverable quarantine operations expire after seven days.
