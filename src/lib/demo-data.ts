import type {
  AuditEvent,
  BenchmarkRun,
  DashboardSnapshot,
  FanCurveProfile,
  LaunchProfile,
  MetricSeries,
  ModelAsset,
  ProviderSnapshot,
  SystemSnapshot,
} from "./types";

function buildSeries(kind: MetricSeries["kind"], label: string, unit: string, color: string, base: number, points: number[]): MetricSeries {
  const now = Date.now();
  return {
    kind,
    label,
    unit,
    color,
    points: points.map((value, index) => ({
      timestamp: new Date(now - (points.length - index - 1) * 5 * 60_000).toISOString(),
      value: base + value,
    })),
  };
}

const provider: ProviderSnapshot = {
  status: "ready",
  model: "gpu45-llm",
  providerUrl: "http://127.0.0.1:30000",
  activeRequests: 0,
  promptTokens: 569,
  completionTokens: 490,
  tokensPerSecond: 34.7,
  metrics: {
    requests_processing: 0,
    prompt_tokens_total: 569,
    tokens_predicted_total: 490,
  },
  lastError: null,
  processStatus: "active",
  proxyReady: true,
  backendReady: true,
  resourceOwner: null,
  transition: null,
};

const system: SystemSnapshot = {
  cpuUsage: 18.5,
  loadAverage: [1.52, 1.21, 0.88],
  ramUsedBytes: 18 * 1024 ** 3,
  ramTotalBytes: 32 * 1024 ** 3,
  diskUsedBytes: 420 * 1024 ** 3,
  diskFreeBytes: 180 * 1024 ** 3,
  diskTotalBytes: 600 * 1024 ** 3,
  gpuTempEdgeC: 29,
  gpuTempJunctionC: 34,
  gpuTempMemoryC: 28,
  gpuPowerW: 33,
  gpuUsage: 2,
  vramUsedBytes: 27_348_127_744,
  vramTotalBytes: 32_195_477_504,
  fanPwm: 150,
  fanRpm: 2_220,
  fanLabel: "fan3",
};

const models: ModelAsset[] = [
  {
    name: "Qwen3.6-27B-UD-Q4_K_XL.gguf",
    path: "/models/huggingface/hub/models--unsloth--Qwen3.6-27B-MTP-GGUF/snapshots/.../Qwen3.6-27B-UD-Q4_K_XL.gguf",
    sizeBytes: 17_898_102_784,
    repo: "unsloth/Qwen3.6-27B-MTP-GGUF",
    revision: "main",
    multimodal: true,
    projectorPath: "/models/huggingface/hub/models--unsloth--Qwen3.6-27B-MTP-GGUF/snapshots/.../mmproj-BF16.gguf",
    active: true,
  },
];

const profiles: LaunchProfile[] = [
  {
    name: "gpu45-default",
    description: "Current Qwen3.6 multimodal profile",
    modelPath: models[0].path,
    mmprojPath: models[0].projectorPath ?? undefined,
    host: "0.0.0.0",
    port: 30000,
    ctxSize: 262144,
    gpuLayers: "all",
    batchSize: 1024,
    uBatchSize: 256,
    cacheRamMiB: 8192,
    cacheTypeK: "q4_0",
    cacheTypeV: "q4_0",
    cacheReuse: 1024,
    specType: "draft-mtp",
    specDraftNMax: 2,
    flashAttention: "on",
    imageMinTokens: 1024,
    metrics: true,
    jinja: true,
    active: true,
  },
];

const fanCurves: FanCurveProfile[] = [
  {
    name: "Quiet Guard",
    description: "Best tested balance. Quiet idle, delayed ramp, full fan before junction can pass 90C.",
    fanStopBelowC: null,
    fanStartAtC: null,
    idlePwm: 70,
    startupPwm: 255,
    startupSeconds: 6,
    channels: [
      { pwm: "pwm3", fan: "fan3_input", label: "gpu-fan-a" },
      { pwm: "pwm4", fan: "fan4_input", label: "gpu-fan-b" },
    ],
    points: [
      { temperatureC: 35, pwm: 70 },
      { temperatureC: 50, pwm: 75 },
      { temperatureC: 60, pwm: 95 },
      { temperatureC: 70, pwm: 140 },
      { temperatureC: 78, pwm: 190 },
      { temperatureC: 84, pwm: 255 },
      { temperatureC: 100, pwm: 255 },
    ],
    active: true,
  },
];

const benchmarks: BenchmarkRun[] = [
  {
    id: "demo-bench-1",
    modelName: "gpu45-llm",
    prompt: "Describe the GPU45 appliance in one sentence.",
    totalTokens: 1320,
    promptTokens: 750,
    completionTokens: 570,
    promptTokensPerSecond: 229.4,
    generationTokensPerSecond: 25.3,
    durationMs: 25_790,
    peakGpuTempC: 58,
    peakVramBytes: 28_200_000_000,
    notes: "Demo run",
    createdAt: new Date().toISOString(),
  },
];

const audit: AuditEvent[] = [
  {
    id: "demo-audit-1",
    action: "provider.refresh",
    subject: "gpu45",
    details: "Loaded multimodal model with mmproj",
    createdAt: new Date().toISOString(),
  },
];

export const demoSnapshot: DashboardSnapshot = {
  collectedAt: new Date().toISOString(),
  provider,
  system,
  models,
  profiles,
  fanCurves,
  benchmarks,
  audit,
  logs: [
    "2026-06-26T15:55:35Z llama_server: model loaded",
    "2026-06-26T15:55:35Z llama_server: server is listening on http://0.0.0.0:30000",
  ],
  charts: {
    gpuTempEdge: buildSeries("gpu_temp_edge", "GPU edge temp", "C", "#2dd4bf", 0, [29, 30, 31, 31, 32, 32, 33, 34, 34, 33, 32, 31]),
    gpuTempJunction: buildSeries("gpu_temp_junction", "GPU junction temp", "C", "#f43f5e", 0, [34, 35, 36, 37, 38, 39, 40, 41, 40, 39, 38, 37]),
    gpuTempMemory: buildSeries("gpu_temp_memory", "GPU memory temp", "C", "#f59e0b", 0, [28, 29, 30, 31, 32, 33, 34, 35, 35, 34, 33, 32]),
    gpuPower: buildSeries("gpu_power_w", "GPU power", "W", "#fb923c", 0, [28, 30, 32, 33, 34, 36, 37, 38, 37, 35, 34, 33]),
    gpuUsage: buildSeries("gpu_usage", "GPU usage", "%", "#60a5fa", 0, [2, 5, 8, 11, 13, 12, 9, 7, 6, 4, 3, 2]),
    vramUsed: buildSeries("vram_used", "VRAM used", "GB", "#a78bfa", 0, [26.5, 26.8, 27.1, 27.3, 27.8, 28.0, 27.9, 27.7, 27.4, 27.2, 27.1, 27.0]),
    vramTotal: buildSeries("vram_total", "VRAM total", "GB", "#c084fc", 32.0, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    vramFree: buildSeries("vram_free", "VRAM free", "GB", "#8b5cf6", 4.0, [0.2, 0.1, 0.0, -0.1, -0.2, -0.2, -0.3, -0.4, -0.3, -0.2, -0.1, 0.0]),
    cpuUsage: buildSeries("cpu_usage", "CPU usage", "%", "#f59e0b", 0, [15, 19, 22, 18, 17, 21, 24, 27, 23, 20, 18, 16]),
    ramUsage: buildSeries("ram_used", "RAM used", "GB", "#ef4444", 0, [17, 18, 18.2, 18.4, 18.5, 18.7, 18.9, 19.1, 18.8, 18.5, 18.4, 18.3]),
    diskUsed: buildSeries("disk_used", "Disk used", "GB", "#84cc16", 420, [0, 1, 2, 2, 3, 3, 4, 4, 5, 5, 5, 6]),
    diskFree: buildSeries("disk_free", "Disk free", "GB", "#84cc16", 180, [0, -1, -2, -2, -3, -3, -4, -4, -5, -5, -5, -6]),
    fanPwm: buildSeries("fan_pwm", "Fan PWM", "pwm", "#f97316", 0, [128, 135, 150, 160, 170, 180, 190, 210, 220, 230, 240, 255]),
    fanRpm: buildSeries("fan_rpm", "Fan RPM", "rpm", "#f59e0b", 0, [1800, 1900, 2100, 2400, 2600, 2800, 3000, 3200, 3400, 3600, 3800, 4000]),
    tokensPerSecond: buildSeries("tokens_per_second", "Tokens/sec", "tok/s", "#38bdf8", 0, [31, 32, 34, 35, 36, 35, 34, 33, 32, 31, 30, 29]),
  },
};
