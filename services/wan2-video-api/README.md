# GPU45 LTX Video Service

This job-based controller serves the appliance's LTX-2.3 text-to-video and
image-to-video profiles. The lightweight API runs from
`/opt/gpu45-video-api-venv`; generation runs through the ROCm ComfyUI stack in
`/opt/hunyuan-video-1.5` and `/opt/hunyuan-video-venv`.

Persistent job metadata, uploads, logs, and outputs remain under
`/models/wan2-video` for backward compatibility. The directory name is legacy;
it does not imply that WAN model weights are installed.

Install or refresh the LTX integration with:

```bash
sudo /opt/gpu45-provider-appliance/scripts/install-ltx23-video-profile.sh
```

The webapp proxies the loopback API through `/api/video`.
