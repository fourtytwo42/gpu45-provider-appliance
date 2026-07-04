# Image API

Local image generation service for the GPU45 appliance. It uses Diffusers on ROCm,
stores generated PNG files, and exposes persistent job records to the Next.js UI.

Default port: `8030`
Default data dir: `/models/image-gen`

The service stops `llama-openai.service` during generation and restarts it after
the job to free GPU VRAM for image models.
