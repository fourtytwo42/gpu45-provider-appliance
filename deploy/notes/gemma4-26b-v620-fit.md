# Gemma 4 26B A4B Q8 V620 Fit

On the 32 GB Radeon Pro V620, the Q8 target plus MTP draft cannot start with
the former 256K context, a 4096 batch, and a 1024 ubatch. llama.cpp fails
while allocating a 1.65 GB ROCm prefill graph buffer and systemd restarts the
server indefinitely.

The verified profile is 128K context with `batchSize=1024` and
`uBatchSize=512`. It retains Q8 weights, q4 K/V cache, and MTP, and completed
a model-load and `/v1/models` smoke test on 2026-07-17.

Apply the idempotent correction with:

```bash
sudo /opt/gpu45/current/scripts/tune-gemma4-26b-profile.sh
```
