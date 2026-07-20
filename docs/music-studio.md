# GPU45 Music Studio

Music Studio runs through the loopback-only `gpu45-music-api.service`. The
controller owns persistent job state while ACE-Step and LeVo execute in isolated
worker environments under a central GPU resource lease.

## ACE-Step 1.5

The installation is pinned in `config/music-models.json`. Reproduce it with:

```bash
sudo /opt/gpu45-provider-appliance/scripts/install-ace-step-music.sh --all
```

The installer uses an isolated Python 3.12 runtime and ROCm PyTorch environment.
It does not change the appliance kernel, global ROCm packages, or existing model
services. Model revisions and post-download checksums are retained under
`/models/music/ace-step/`.

Runtime profiles:

- XL Turbo + 4B LM: eight-step default generation.
- XL SFT + 4B LM: quality-focused generation.
- XL Base + 4B LM: cover, repaint, complete, layer, and extraction workflows.

## LeVo 2

LeVo is experimental and restricted to academic, research, and educational use.
It remains unavailable until the pinned AMD four-phase runtime passes a 60-second
hardware validation on the V620. The console requires acceptance of the exact
license hash before a LeVo job can be created.

Install and validate it separately:

```bash
sudo /opt/gpu45-provider-appliance/scripts/install-levo2-music.sh --all
sudo -u gpu45-music --preserve-env=GPU45_RESOURCE_MANAGER_TOKEN,GPU45_RESOURCE_MANAGER_URL \
  /opt/gpu45-provider-appliance/scripts/validate-levo2-music.py
```

The validation runner acquires a real Music resource lease and only marks the
profile ready after a valid approximately 60-second output finishes within the
10-minute retention gate.
