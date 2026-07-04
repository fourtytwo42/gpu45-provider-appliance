# GPU45 Wan2.2 Video Service

This service wraps the official Wan2.2 repository for the GPU45 appliance.

Default target:

- model: `Wan-AI/Wan2.2-TI2V-5B`
- task: `ti2v-5B`
- recommended flags: `--offload_model True --convert_model_dtype --t5_cpu`

The service is intentionally job-based because video generation is long-running and uses the GPU. Jobs stop `llama-openai.service` before generation and restart it afterward.

Install with:

```bash
sudo /opt/gpu45-provider-appliance/scripts/install-wan2-video-service.sh
```

The webapp proxies this API through `/api/video`.
