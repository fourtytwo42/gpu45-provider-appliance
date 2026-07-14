export type RuntimeMode = "live" | "mock";

export type ProviderStatus =
  | "unloaded"
  | "starting"
  | "ready"
  | "busy"
  | "releasing"
  | "restoring"
  | "failed";

export type ProviderProcessStatus = "active" | "activating" | "deactivating" | "inactive" | "failed" | "unknown";

export type MetricKind =
  | "gpu_temp_edge"
  | "gpu_temp_junction"
  | "gpu_temp_memory"
  | "gpu_power_w"
  | "gpu_usage"
  | "vram_used"
  | "vram_total"
  | "vram_free"
  | "cpu_usage"
  | "ram_used"
  | "ram_total"
  | "disk_used"
  | "disk_free"
  | "disk_total"
  | "fan_rpm"
  | "fan_pwm"
  | "tokens_per_second"
  | "prompt_tokens"
  | "completion_tokens";

export type SeriesPoint = {
  timestamp: string;
  value: number;
};

export type MetricSeries = {
  kind: MetricKind;
  label: string;
  unit: string;
  color: string;
  points: SeriesPoint[];
};

export type ProviderSnapshot = {
  status: ProviderStatus;
  model: string;
  providerUrl: string;
  activeRequests: number;
  promptTokens: number;
  completionTokens: number;
  tokensPerSecond: number;
  metrics: Record<string, number>;
  lastError?: string | null;
  processStatus: ProviderProcessStatus;
  proxyReady: boolean;
  backendReady: boolean;
  resourceOwner: string | null;
  transition: "releasing" | "restoring" | "starting" | null;
};

export type SystemSnapshot = {
  cpuUsage: number;
  loadAverage: [number, number, number];
  ramUsedBytes: number;
  ramTotalBytes: number;
  diskUsedBytes: number;
  diskFreeBytes: number;
  diskTotalBytes: number;
  gpuTempEdgeC: number | null;
  gpuTempJunctionC: number | null;
  gpuTempMemoryC: number | null;
  gpuPowerW: number | null;
  gpuUsage: number | null;
  vramUsedBytes: number | null;
  vramTotalBytes: number | null;
  fanPwm: number | null;
  fanRpm: number | null;
  fanLabel: string | null;
};

export type ModelAsset = {
  name: string;
  path: string;
  sizeBytes: number;
  repo?: string | null;
  revision?: string | null;
  multimodal: boolean;
  projectorPath?: string | null;
  draftPath?: string | null;
  active: boolean;
  served?: boolean;
  servedAlias?: string | null;
  defaultModel?: boolean;
  launchProfile?: LaunchProfile | null;
};

export type ApiKeyRecord = {
  id: string;
  name?: string | null;
  keyPrefix: string;
  expiresAt?: string | null;
  suspendedAt?: string | null;
  lastUsedAt?: string | null;
  requestCount: number;
  promptTokens: number;
  completionTokens: number;
  createdAt: string;
  models: Array<{ model: string; requests: number; promptTokens: number; completionTokens: number }>;
};

export type LaunchProfile = {
  name: string;
  description?: string | null;
  modelPath: string;
  mmprojPath?: string | null;
  modelDraftPath?: string | null;
  host: string;
  port: number;
  ctxSize: number;
  gpuLayers: string;
  batchSize: number;
  uBatchSize: number;
  cacheRamMiB: number;
  cacheTypeK: string;
  cacheTypeV: string;
  cacheReuse: number;
  specType: string;
  specDraftNMax: number;
  flashAttention: string;
  backend?: "rocm" | "vulkan";
  serverBinary?: string | null;
  runtimeLibraryPath?: string | null;
  fanBoostOnBusy?: boolean;
  imageMinTokens: number;
  metrics: boolean;
  jinja: boolean;
  active: boolean;
};

export type FanPoint = {
  temperatureC: number;
  pwm: number;
};

export type FanChannel = {
  pwm: string;
  fan: string;
  label: string;
};

export type FanCurveProfile = {
  name: string;
  description?: string | null;
  fanStopBelowC?: number | null;
  fanStartAtC?: number | null;
  idlePwm?: number;
  startupPwm?: number;
  startupSeconds?: number;
  channels?: FanChannel[];
  points: FanPoint[];
  active: boolean;
};

export type BenchmarkRun = {
  id: string;
  modelName: string;
  prompt: string;
  totalTokens: number;
  promptTokens: number;
  completionTokens: number;
  promptTokensPerSecond: number;
  generationTokensPerSecond: number;
  durationMs: number;
  peakGpuTempC?: number | null;
  peakVramBytes?: number | null;
  notes?: string | null;
  optionsJson?: string | null;
  createdAt: string;
};

export type LiveTelemetry = {
  collectedAt: string;
  provider: ProviderSnapshot;
  system: SystemSnapshot;
};

export type DownloadJob = {
  id: string;
  repoId: string;
  fileName: string;
  revision: string;
  status: "queued" | "downloading" | "completed" | "failed" | "cancelled";
  bytesDownloaded: number;
  totalBytes: number;
  targetPath: string;
  error?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type AuditEvent = {
  id: string;
  action: string;
  subject: string;
  details: string;
  createdAt: string;
};

export type DashboardSnapshot = {
  collectedAt: string;
  provider: ProviderSnapshot;
  system: SystemSnapshot;
  models: ModelAsset[];
  profiles: LaunchProfile[];
  fanCurves: FanCurveProfile[];
  benchmarks: BenchmarkRun[];
  audit: AuditEvent[];
  logs: string[];
  charts: {
    gpuTempEdge: MetricSeries;
    gpuTempJunction: MetricSeries;
    gpuTempMemory: MetricSeries;
    gpuPower: MetricSeries;
    gpuUsage: MetricSeries;
    vramUsed: MetricSeries;
    vramTotal: MetricSeries;
    vramFree: MetricSeries;
    cpuUsage: MetricSeries;
    ramUsage: MetricSeries;
    diskUsed: MetricSeries;
    diskFree: MetricSeries;
    fanPwm: MetricSeries;
    fanRpm: MetricSeries;
    tokensPerSecond: MetricSeries;
  };
};
