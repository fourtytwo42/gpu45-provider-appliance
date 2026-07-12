import { z } from "zod";
import type { RuntimeMode } from "./types";

const envSchema = z.object({
  GPU45_MODE: z.enum(["live", "mock"]).optional(),
  GPU45_PROVIDER_URL: z.string().default("http://127.0.0.1:30001"),
  GPU45_BACKEND_URL: z.string().default("http://127.0.0.1:30000"),
  GPU45_TTS_URL: z.string().default("http://127.0.0.1:8000"),
  GPU45_POCKET_TTS_URL: z.string().default("http://127.0.0.1:8002"),
  GPU45_VIDEO_URL: z.string().default("http://127.0.0.1:8010"),
  GPU45_WHISPER_URL: z.string().default("http://127.0.0.1:8020"),
  GPU45_IMAGE_URL: z.string().default("http://127.0.0.1:8030"),
  GPU45_SEARXNG_URL: z.string().default("http://127.0.0.1:8888"),
  GPU45_RESOURCE_MANAGER_URL: z.string().default("http://127.0.0.1:8040"),
  GPU45_RESOURCE_MANAGER_TOKEN: z.string().optional(),
  GPU45_PROVIDER_SERVICE: z.string().default("llama-openai.service"),
  GPU45_FAN_SERVICE: z.string().default("gpu45-v620-fan-controller.service"),
  GPU45_PROXMOX_HOST: z.string().optional(),
  GPU45_PROXMOX_USER: z.string().default("root"),
  GPU45_PROXMOX_PASSWORD: z.string().optional(),
  GPU45_PROXMOX_PORT: z.coerce.number().int().positive().default(22),
  GPU45_GPU_CONTAINER_ID: z.coerce.number().int().positive().default(103),
  GPU45_MODEL_ROOT: z.string().default("/models/huggingface/hub"),
  GPU45_STORAGE_ROOT: z.string().default("/models"),
  GPU45_GPU_DEVICE_PATH: z.string().default("/sys/class/drm/card1/device"),
  GPU45_GPU_HWMON_PATH: z.string().default("/sys/class/drm/card1/device/hwmon/hwmon8"),
  GPU45_FAN_SCRIPT: z.string().default("/usr/local/sbin/gpu45-v620-fan-controller"),
  GPU45_PROVIDER_SCRIPT: z.string().default("/usr/local/bin/gpu45-llm-server"),
  GPU45_PROVIDER_PROFILE_PATH: z.string().default("/etc/gpu45/provider-profile.json"),
  GPU45_FAN_PROFILE_PATH: z.string().default("/etc/gpu45/fan-curve.json"),
  GPU45_FAN_STATE_PATH: z.string().default("/etc/gpu45/fan-state.json"),
  GPU45_DATA_DIR: z.string().default("./.gpu45-data"),
  GPU45_STORAGE_THRESHOLD_GB: z.coerce.number().default(50),
  GPU45_DOWNLOAD_STAGING: z.string().default("/models/huggingface/staging"),
  GPU45_BENCHMARK_PROMPT: z
    .string()
    .default("Describe this system in one concise sentence."),
  GPU45_HF_TOKEN: z.string().optional(),
});

const parsedEnv = envSchema.parse(process.env);

export type ApplianceConfig = {
  mode: RuntimeMode;
  providerUrl: string;
  backendUrl: string;
  ttsUrl: string;
  pocketTtsUrl: string;
  videoUrl: string;
  whisperUrl: string;
  imageUrl: string;
  searxngUrl: string;
  resourceManagerUrl: string;
  resourceManagerToken?: string;
  providerService: string;
  fanService: string;
  proxmoxHost?: string;
  proxmoxUser: string;
  proxmoxPassword?: string;
  proxmoxPort: number;
  gpuContainerId: number;
  modelRoot: string;
  storageRoot: string;
  gpuDevicePath: string;
  gpuHwmonPath: string;
  fanScript: string;
  providerScript: string;
  providerProfilePath: string;
  fanProfilePath: string;
  fanStatePath: string;
  dataDir: string;
  storageThresholdGb: number;
  downloadStaging: string;
  benchmarkPrompt: string;
  hfToken?: string;
};

export function getConfig(): ApplianceConfig {
  const defaultMode: RuntimeMode = process.env.NODE_ENV === "production" ? "live" : "mock";
  return {
    mode: parsedEnv.GPU45_MODE ?? defaultMode,
    providerUrl: parsedEnv.GPU45_PROVIDER_URL,
    backendUrl: parsedEnv.GPU45_BACKEND_URL,
    ttsUrl: parsedEnv.GPU45_TTS_URL,
    pocketTtsUrl: parsedEnv.GPU45_POCKET_TTS_URL,
    videoUrl: parsedEnv.GPU45_VIDEO_URL,
    whisperUrl: parsedEnv.GPU45_WHISPER_URL,
    imageUrl: parsedEnv.GPU45_IMAGE_URL,
    searxngUrl: parsedEnv.GPU45_SEARXNG_URL,
    resourceManagerUrl: parsedEnv.GPU45_RESOURCE_MANAGER_URL,
    resourceManagerToken: parsedEnv.GPU45_RESOURCE_MANAGER_TOKEN,
    providerService: parsedEnv.GPU45_PROVIDER_SERVICE,
    fanService: parsedEnv.GPU45_FAN_SERVICE,
    proxmoxHost: parsedEnv.GPU45_PROXMOX_HOST,
    proxmoxUser: parsedEnv.GPU45_PROXMOX_USER,
    proxmoxPassword: parsedEnv.GPU45_PROXMOX_PASSWORD,
    proxmoxPort: parsedEnv.GPU45_PROXMOX_PORT,
    gpuContainerId: parsedEnv.GPU45_GPU_CONTAINER_ID,
    modelRoot: parsedEnv.GPU45_MODEL_ROOT,
    storageRoot: parsedEnv.GPU45_STORAGE_ROOT,
    gpuDevicePath: parsedEnv.GPU45_GPU_DEVICE_PATH,
    gpuHwmonPath: parsedEnv.GPU45_GPU_HWMON_PATH,
    fanScript: parsedEnv.GPU45_FAN_SCRIPT,
    providerScript: parsedEnv.GPU45_PROVIDER_SCRIPT,
    providerProfilePath: parsedEnv.GPU45_PROVIDER_PROFILE_PATH,
    fanProfilePath: parsedEnv.GPU45_FAN_PROFILE_PATH,
    fanStatePath: parsedEnv.GPU45_FAN_STATE_PATH,
    dataDir: parsedEnv.GPU45_DATA_DIR,
    storageThresholdGb: parsedEnv.GPU45_STORAGE_THRESHOLD_GB,
    downloadStaging: parsedEnv.GPU45_DOWNLOAD_STAGING,
    benchmarkPrompt: parsedEnv.GPU45_BENCHMARK_PROMPT,
    hfToken: parsedEnv.GPU45_HF_TOKEN,
  };
}

export function isLiveRuntime(): boolean {
  return getConfig().mode === "live";
}
