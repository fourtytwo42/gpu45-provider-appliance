import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { prisma } from "./db";
import { getConfig, isLiveRuntime } from "./config";
import { runBash, shQuote } from "./command";
import { demoSnapshot } from "./demo-data";
import { listModelFiles, readContainerText, readHostText, runHostCommand } from "./proxmox";
import {
  parseCurvePoints,
} from "./parsers";
import { collectProviderRuntimeSnapshot } from "./provider-state";
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
  LiveTelemetry,
} from "./types";
import { syncModelCatalog } from "./model-catalog";

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function toMetricSeries(
  kind: MetricSeries["kind"],
  label: string,
  unit: string,
  color: string,
  points: { timestamp: string; value: number }[],
): MetricSeries {
  return { kind, label, unit, color, points };
}

async function readText(filePath: string): Promise<string | null> {
  try {
    return await fs.readFile(filePath, "utf8");
  } catch {
    return null;
  }
}

async function readTextMaybeRemote(filePath: string): Promise<string | null> {
  const remote = await readContainerText(filePath);
  if (remote !== null) return remote;

  const local = await readText(filePath);
  if (local !== null) return local;

  const cfg = getConfig();
  return runBash(`pct exec ${cfg.gpuContainerId} -- cat ${shQuote(filePath)}`).catch(() => null);
}

async function readJsonMaybeRemote<T>(filePath: string): Promise<T | null> {
  const text = await readTextMaybeRemote(filePath);
  if (!text) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

async function readNumberMaybeRemote(filePath: string, scale = 1): Promise<number | null> {
  const text = await readTextMaybeRemote(filePath);
  if (!text) return null;
  const value = Number(text.trim());
  return Number.isFinite(value) ? value / scale : null;
}

async function resolveAmdgpuHwmonPath(): Promise<string> {
  const cfg = getConfig();
  const configuredName = await readTextMaybeRemote(path.join(cfg.gpuHwmonPath, "name"));
  if (configuredName?.trim().toLowerCase() === "amdgpu") {
    return cfg.gpuHwmonPath;
  }

  const candidates = [
    path.join(cfg.gpuDevicePath, "hwmon"),
    "/sys/class/hwmon",
  ];

  for (const root of candidates) {
    const entries = await fs.readdir(root, { withFileTypes: true }).catch(() => []);
    for (const entry of entries) {
      if (!entry.isDirectory() && !entry.isSymbolicLink()) continue;
      const candidate = path.join(root, entry.name);
      const name = await readTextMaybeRemote(path.join(candidate, "name"));
      if (name?.trim().toLowerCase() === "amdgpu") {
        return candidate;
      }
    }
  }

  return cfg.gpuHwmonPath;
}

type FanStateSnapshot = {
  label?: string | null;
  maxTempC?: number | null;
  pwm?: number | null;
  rpm?: number | null;
  status?: string | null;
  temperaturesC?: {
    edge?: number | null;
    junction?: number | null;
    mem?: number | null;
  } | null;
  updatedAt?: string | null;
};

export async function collectProviderSnapshot(): Promise<ProviderSnapshot> {
  return collectProviderRuntimeSnapshot();
}

export async function collectSystemSnapshot(): Promise<SystemSnapshot> {
  const cfg = getConfig();
  const gpuHwmonPath = await resolveAmdgpuHwmonPath();
  const [cpuUsage, loadAverage, ramSnapshot, dfText, fan, gpuPowerW, gpuUsage, gpuTempEdgeFromFile, gpuTempJunctionFromFile, gpuTempMemoryFromFile, vramUsedBytes, vramTotalBytes] =
    await Promise.all([
      collectCpuUsage(),
      collectLoadAverage(),
      collectRamSnapshot(),
      runHostCommand(`df -B1 ${shQuote(cfg.storageRoot)} ${shQuote(cfg.modelRoot)} 2>/dev/null || df -B1 /`).catch(() => ""),
      collectFanSnapshot(),
      readNumberMaybeRemote(`${gpuHwmonPath}/power1_average`, 1_000_000),
      readNumberMaybeRemote(`${cfg.gpuDevicePath}/gpu_busy_percent`),
      readNumberMaybeRemote(`${gpuHwmonPath}/temp1_input`, 1_000),
      readNumberMaybeRemote(`${gpuHwmonPath}/temp2_input`, 1_000),
      readNumberMaybeRemote(`${gpuHwmonPath}/temp3_input`, 1_000),
      readNumberMaybeRemote(`${cfg.gpuDevicePath}/mem_info_vram_used`),
      readNumberMaybeRemote(`${cfg.gpuDevicePath}/mem_info_vram_total`),
    ]);
  const disk = parseDfOutput(dfText ?? "");
  return {
    cpuUsage,
    loadAverage,
    ramUsedBytes: ramSnapshot.usedBytes,
    ramTotalBytes: ramSnapshot.totalBytes,
    diskUsedBytes: disk.usedBytes,
    diskFreeBytes: disk.freeBytes,
    diskTotalBytes: disk.totalBytes,
    gpuTempEdgeC: fan.temperaturesC?.edge ?? gpuTempEdgeFromFile ?? null,
    gpuTempJunctionC: fan.temperaturesC?.junction ?? gpuTempJunctionFromFile ?? null,
    gpuTempMemoryC: fan.temperaturesC?.mem ?? gpuTempMemoryFromFile ?? null,
    gpuPowerW: gpuPowerW ?? null,
    gpuUsage: gpuUsage ?? null,
    vramUsedBytes: vramUsedBytes ?? null,
    vramTotalBytes: vramTotalBytes ?? null,
    fanPwm: fan.pwm ?? null,
    fanRpm: fan.rpm ?? null,
    fanLabel: fan.label ?? null,
  };
}

async function collectCpuUsage(): Promise<number> {
  const remoteStart = await readHostText("/proc/stat");
  if (remoteStart !== null) {
    await new Promise((resolve) => setTimeout(resolve, 100));
    const remoteEnd = await readHostText("/proc/stat");
    if (remoteEnd !== null) {
      const start = parseCpuStat(remoteStart);
      const end = parseCpuStat(remoteEnd);
      if (start && end) {
        return calculateCpuUsage(start, end);
      }
    }
  }

  return runCpuUsageLocal();
}

async function collectLoadAverage(): Promise<[number, number, number]> {
  const text = await readHostText("/proc/loadavg");
  if (text) {
    const values = text.trim().split(/\s+/).slice(0, 3).map((value) => Number(value));
    if (values.length === 3 && values.every((value) => Number.isFinite(value))) {
      return values as [number, number, number];
    }
  }
  return os.loadavg() as [number, number, number];
}

async function collectRamSnapshot(): Promise<{ usedBytes: number; totalBytes: number }> {
  const text = await readHostText("/proc/meminfo");
  if (text) {
    const total = text.match(/^MemTotal:\s+(\d+)\s+kB$/m);
    const available = text.match(/^MemAvailable:\s+(\d+)\s+kB$/m);
    if (total && available) {
      const totalBytes = Number(total[1]) * 1024;
      const availableBytes = Number(available[1]) * 1024;
      if (Number.isFinite(totalBytes) && Number.isFinite(availableBytes)) {
        return {
          usedBytes: totalBytes - availableBytes,
          totalBytes,
        };
      }
    }
  }
  return {
    usedBytes: os.totalmem() - os.freemem(),
    totalBytes: os.totalmem(),
  };
}

function parseCpuStat(text: string): { total: number; idle: number } | null {
  const line = text.split(/\r?\n/).find((entry) => entry.startsWith("cpu "));
  if (!line) return null;
  const values = line
    .trim()
    .split(/\s+/)
    .slice(1)
    .map((value) => Number(value));
  if (values.some((value) => !Number.isFinite(value))) return null;
  const idle = (values[3] ?? 0) + (values[4] ?? 0);
  const total = values.reduce((sum, value) => sum + value, 0);
  return { total, idle };
}

function calculateCpuUsage(start: { total: number; idle: number }, end: { total: number; idle: number }): number {
  const total = end.total - start.total;
  const idle = end.idle - start.idle;
  return total > 0 ? clamp(100 - (idle / total) * 100, 0, 100) : 0;
}

async function runCpuUsageLocal(): Promise<number> {
  const start = os.cpus();
  await new Promise((resolve) => setTimeout(resolve, 10));
  const end = os.cpus();
  let idle = 0;
  let total = 0;
  for (let i = 0; i < start.length; i += 1) {
    const s = start[i].times;
    const e = end[i].times;
    idle += e.idle - s.idle;
    total += Object.values(e).reduce((a, b) => a + b, 0) - Object.values(s).reduce((a, b) => a + b, 0);
  }
  return total > 0 ? clamp(100 - (idle / total) * 100, 0, 100) : 0;
}

function parseDfOutput(text: string): { usedBytes: number; freeBytes: number; totalBytes: number } {
  const lines = text.split(/\r?\n/).filter(Boolean);
  const rows = lines.slice(1).map((line) => line.split(/\s+/).filter(Boolean));
  const selected = rows.find((row) => row.length >= 6) ?? rows[0] ?? [];
  const total = Number(selected[1] ?? 0);
  const used = Number(selected[2] ?? 0);
  const avail = Number(selected[3] ?? 0);
  return {
    usedBytes: used,
    freeBytes: avail,
    totalBytes: total,
  };
}

async function collectFanSnapshot(): Promise<FanStateSnapshot> {
  const cfg = getConfig();
  const state =
    (await readJsonMaybeRemote<FanStateSnapshot>(cfg.fanStatePath).catch(() => null)) ??
    (await readJsonMaybeRemote<FanStateSnapshot>("/etc/gpu45/fan-state.json").catch(() => null));
  if (state && (state.pwm !== undefined || state.rpm !== undefined || state.temperaturesC)) {
    return {
      pwm: state.pwm ?? null,
      rpm: state.rpm ?? null,
      label: state.label ?? "fan-state",
      temperaturesC: state.temperaturesC
        ? {
            edge: state.temperaturesC.edge ?? null,
            junction: state.temperaturesC.junction ?? null,
            mem: state.temperaturesC.mem ?? null,
          }
        : null,
    };
  }

  if (!await readHostText("/usr/local/sbin/gpu45-v620-fan-controller")) return { pwm: null, rpm: null, label: null };
  const hwmons = await fs.readdir("/sys/class/hwmon").catch(() => []);
  let fanHwmon: string | null = null;
  for (const entry of hwmons) {
    const namePath = path.join("/sys/class/hwmon", entry, "name");
    const name = await readText(namePath);
    if (isFanControllerHwmonName(name)) {
      fanHwmon = path.join("/sys/class/hwmon", entry);
      break;
    }
  }
  if (!fanHwmon) {
    for (const entry of hwmons) {
      const candidate = path.join("/sys/class/hwmon", entry);
      const pwmText = await readText(path.join(candidate, "pwm3"));
      const rpmText = await readText(path.join(candidate, "fan3_input"));
      if (pwmText !== null || rpmText !== null) {
        fanHwmon = candidate;
        break;
      }
    }
  }
  if (!fanHwmon) return { pwm: null, rpm: null, label: null };
  const pwmCandidates = ["pwm1", "pwm2", "pwm3", "pwm4"];
  const rpmCandidates = ["fan1_input", "fan2_input", "fan3_input", "fan4_input"];
  let pwmText: string | null = null;
  for (const candidate of pwmCandidates) {
    pwmText = await readText(path.join(fanHwmon, candidate));
    if (pwmText !== null) break;
  }
  let rpmText: string | null = null;
  for (const candidate of rpmCandidates) {
    rpmText = await readText(path.join(fanHwmon, candidate));
    if (rpmText !== null) break;
  }
  return {
    pwm: pwmText ? Number(pwmText) : null,
    rpm: rpmText ? Number(rpmText) : null,
    label: path.basename(fanHwmon),
  };
}

export function isFanControllerHwmonName(name: string | null | undefined): boolean {
  const normalized = name?.trim().toLowerCase();
  return normalized === "nct6687" || normalized?.includes("nct6687") || false;
}

async function collectModelAssets(): Promise<ModelAsset[]> {
  const cfg = getConfig();
  const profile = await readJsonFile<{ modelPath?: string; mmprojPath?: string; modelDraftPath?: string }>(cfg.providerProfilePath);
  const script = await readTextMaybeRemote(cfg.providerScript);
  const activeModel = profile ? profile.modelPath ?? null : script?.match(/-m\s+(\S+)(?:\s|$)/)?.[1] ?? null;
  const activeMmproj = profile ? profile.mmprojPath ?? null : script?.match(/--mmproj\s+(\S+)(?:\s|$)/)?.[1] ?? null;
  const activeDraft = profile ? profile.modelDraftPath ?? null : script?.match(/(?:-md|--model-draft)\s+(\S+)(?:\s|$)/)?.[1] ?? null;
  const assets = await scanModelRoots([cfg.modelRoot, cfg.downloadStaging]);
  return syncModelCatalog(assets.map((asset) => ({
    ...asset,
    active: asset.path === activeModel || asset.path === activeMmproj || asset.path === activeDraft,
    projectorPath: asset.path === activeModel ? activeMmproj : asset.projectorPath,
    draftPath: asset.path === activeModel ? activeDraft : null,
  })));
}

async function collectLaunchProfiles(models: ModelAsset[]): Promise<LaunchProfile[]> {
  const cfg = getConfig();
  const profile = await readJsonFile<LaunchProfile>(cfg.providerProfilePath);
  const activeModel = models.find((model) => model.active) ?? models[0];
  if (!activeModel) return [];
  const mmprojPath = activeModel.multimodal ? activeModel.path.replace(/\.gguf$/i, "") : null;
  if (profile?.name && profile?.modelPath) {
    return [
      {
        ...profile,
        description: profile.description ?? "Current GPU45 provider profile",
        mmprojPath: profile.mmprojPath ?? mmprojPath,
        active: true,
      },
    ];
  }
  return [
    {
      name: "gpu45-default",
      description: "Current GPU45 provider profile",
      modelPath: activeModel.path,
      mmprojPath,
      modelDraftPath: null,
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
}

async function collectFanCurves(): Promise<FanCurveProfile[]> {
  const cfg = getConfig();
  const profile = await readJsonFile<FanCurveProfile>(cfg.fanProfilePath);
  if (profile?.name && Array.isArray(profile.points)) {
    return [
      {
        name: profile.name,
        description: profile.description ?? null,
        fanStopBelowC: profile.fanStopBelowC ?? null,
        fanStartAtC: profile.fanStartAtC ?? null,
        idlePwm: profile.idlePwm,
        startupPwm: profile.startupPwm,
        startupSeconds: profile.startupSeconds,
        channels: profile.channels,
        points: profile.points,
        active: true,
      },
    ];
  }
  const script = await readTextMaybeRemote("/usr/local/sbin/gpu45-v620-fan-controller");
  if (!script) return [];
  const curveBlock = script.match(/CURVE = \[([\s\S]*?)\]/);
  const points = curveBlock ? parseCurvePoints(curveBlock[1].replace(/[()]/g, "").replace(/\),/g, "\n")) : [];
  return [
    {
      name: "balanced",
      description: "Curve loaded from fan controller script",
      points:
        points.length > 0
          ? points
          : [
              { temperatureC: 0, pwm: 128 },
              { temperatureC: 35, pwm: 128 },
              { temperatureC: 45, pwm: 150 },
              { temperatureC: 55, pwm: 180 },
              { temperatureC: 65, pwm: 220 },
              { temperatureC: 75, pwm: 255 },
            ],
      active: true,
    },
  ];
}

async function collectBenchmarks(): Promise<BenchmarkRun[]> {
  const runs = await prisma.benchmarkRun.findMany({ orderBy: { createdAt: "desc" }, take: 20 });
  return runs.map((run) => ({
    ...run,
    peakVramBytes: run.peakVramBytes ? Number(run.peakVramBytes) : null,
    createdAt: run.createdAt.toISOString(),
  }));
}

async function collectAudit(): Promise<AuditEvent[]> {
  const events = await prisma.auditLog.findMany({ orderBy: { createdAt: "desc" }, take: 20 });
  return events.map((event) => ({
    ...event,
    createdAt: event.createdAt.toISOString(),
  }));
}

async function collectCharts(): Promise<DashboardSnapshot["charts"]> {
  const samples = await prisma.metricSample.findMany({
    where: { capturedAt: { gte: new Date(Date.now() - 6 * 60 * 60 * 1000) } },
    orderBy: { capturedAt: "desc" },
    take: 65000,
  });
  const values = (kind: string) =>
    samples.filter((sample) => sample.kind === kind).reverse().map((sample) => ({
      timestamp: sample.capturedAt.toISOString(),
      value: sample.value,
    }));
  const gpuTempEdgeValues = values("gpu_temp_edge");
  const gpuTempJunctionValues = values("gpu_temp_junction");
  const gpuTempMemoryValues = values("gpu_temp_memory");
  const legacyGpuTempValues = values("gpu_temp");
  return {
    gpuTempEdge: toMetricSeries("gpu_temp_edge", "GPU edge temp", "C", "#2dd4bf", gpuTempEdgeValues.length > 0 ? gpuTempEdgeValues : legacyGpuTempValues),
    gpuTempJunction: toMetricSeries(
      "gpu_temp_junction",
      "GPU junction temp",
      "C",
      "#f43f5e",
      gpuTempJunctionValues.length > 0 ? gpuTempJunctionValues : legacyGpuTempValues,
    ),
    gpuTempMemory: toMetricSeries(
      "gpu_temp_memory",
      "GPU memory temp",
      "C",
      "#f59e0b",
      gpuTempMemoryValues.length > 0 ? gpuTempMemoryValues : legacyGpuTempValues,
    ),
    gpuPower: toMetricSeries("gpu_power_w", "GPU power", "W", "#fb923c", values("gpu_power_w")),
    gpuUsage: toMetricSeries("gpu_usage", "GPU usage", "%", "#60a5fa", values("gpu_usage")),
    vramUsed: toMetricSeries("vram_used", "VRAM used", "GB", "#a78bfa", values("vram_used")),
    vramTotal: toMetricSeries("vram_total", "VRAM total", "GB", "#c084fc", values("vram_total")),
    vramFree: toMetricSeries("vram_free", "VRAM free", "GB", "#8b5cf6", values("vram_free")),
    cpuUsage: toMetricSeries("cpu_usage", "CPU usage", "%", "#f59e0b", values("cpu_usage")),
    ramUsage: toMetricSeries("ram_used", "RAM used", "GB", "#ef4444", values("ram_used")),
    diskUsed: toMetricSeries("disk_used", "Disk used", "GB", "#84cc16", values("disk_used")),
    diskFree: toMetricSeries("disk_free", "Disk free", "GB", "#84cc16", values("disk_free")),
    fanPwm: toMetricSeries("fan_pwm", "Fan PWM", "pwm", "#f97316", values("fan_pwm")),
    fanRpm: toMetricSeries("fan_rpm", "Fan RPM", "rpm", "#f59e0b", values("fan_rpm")),
    tokensPerSecond: toMetricSeries("tokens_per_second", "Tokens/sec", "tok/s", "#38bdf8", values("tokens_per_second")),
  };
}

async function collectProviderLogs(): Promise<string[]> {
  const lines =
    (await runHostCommand(`journalctl -u ${shQuote(getConfig().providerService)} -n 30 --no-pager --output=short-iso`).catch(
      () => "",
    )) ?? "";
  return lines.split(/\r?\n/).filter((line) => line.trim().length > 0).slice(-30);
}

export async function collectLiveTelemetry(): Promise<LiveTelemetry> {
  if (!isLiveRuntime()) {
    return { collectedAt: new Date().toISOString(), provider: demoSnapshot.provider, system: demoSnapshot.system };
  }
  const [provider, system] = await Promise.all([
    collectProviderSnapshot().catch((error) => ({
      ...demoSnapshot.provider,
      status: "failed" as const,
      lastError: error instanceof Error ? error.message : "Provider probe failed",
    })),
    collectSystemSnapshot().catch(() => demoSnapshot.system),
  ]);
  return { collectedAt: new Date().toISOString(), provider, system };
}

async function readJsonFile<T>(filePath: string): Promise<T | null> {
  const text = (await readHostText(filePath)) ?? (await readTextMaybeRemote(filePath));
  if (!text) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

async function scanModelRoots(roots: string[]): Promise<Array<Omit<ModelAsset, "active">>> {
  const results: Array<Omit<ModelAsset, "active">> = [];
  for (const root of roots) {
    await scanModelRoot(root, results);
  }
  return results.sort((left, right) => left.name.localeCompare(right.name));
}

async function scanModelRoot(rootPath: string, results: Array<Omit<ModelAsset, "active">>): Promise<void> {
  const beforeCount = results.length;
  const entries = await fs.readdir(rootPath, { withFileTypes: true }).catch(() => []);
  for (const entry of entries) {
    const entryPath = path.join(rootPath, entry.name);
    if (entry.isDirectory()) {
      await scanModelRoot(entryPath, results);
      continue;
    }
    if (!entry.name.toLowerCase().endsWith(".gguf")) continue;
    const stat = await fs.stat(entryPath).catch(() => null);
    if (!stat) continue;
    const normalized = entryPath.split(path.sep);
    const repoFolder = normalized.find((part) => part.startsWith("models--")) ?? null;
    const repo = repoFolder ? repoFolder.replace(/^models--/, "").replaceAll("--", "/") : null;
    const snapshotsIndex = normalized.findIndex((part) => part === "snapshots");
    const revision = snapshotsIndex >= 0 ? normalized[snapshotsIndex + 1] ?? null : null;
    results.push({
      name: entry.name,
      path: entryPath,
      sizeBytes: stat.size,
      repo,
      revision,
      multimodal: entry.name.toLowerCase().includes("mmproj") || entry.name.toLowerCase().includes("vl"),
      projectorPath: null,
    });
  }
  if (results.length === beforeCount) {
    const remoteEntries = await listModelFiles(rootPath);
    for (const entry of remoteEntries) {
      const normalized = entry.path.split(path.sep);
      const repoFolder = normalized.find((part) => part.startsWith("models--")) ?? null;
      const repo = repoFolder ? repoFolder.replace(/^models--/, "").replaceAll("--", "/") : null;
      const snapshotsIndex = normalized.findIndex((part) => part === "snapshots");
      const revision = snapshotsIndex >= 0 ? normalized[snapshotsIndex + 1] ?? null : null;
      results.push({
        name: path.basename(entry.path),
        path: entry.path,
        sizeBytes: entry.sizeBytes,
        repo,
        revision,
        multimodal: entry.path.toLowerCase().includes("mmproj") || entry.path.toLowerCase().includes("vl"),
        projectorPath: null,
      });
    }
  }
}

export async function collectDashboardSnapshot(): Promise<DashboardSnapshot> {
  if (!isLiveRuntime()) {
    return demoSnapshot;
  }

  const [provider, system, models, profiles, fanCurves, benchmarks, audit, logs] = await Promise.all([
    collectProviderSnapshot().catch(() => demoSnapshot.provider),
    collectSystemSnapshot().catch(() => demoSnapshot.system),
    collectModelAssets().catch(() => demoSnapshot.models),
    Promise.resolve().then(async () => collectLaunchProfiles(await collectModelAssets().catch(() => demoSnapshot.models))).catch(() => demoSnapshot.profiles),
    collectFanCurves().catch(() => demoSnapshot.fanCurves),
    collectBenchmarks().catch(() => demoSnapshot.benchmarks),
    collectAudit().catch(() => demoSnapshot.audit),
    collectProviderLogs().catch(() => []),
  ]);

  const charts = (await collectCharts().catch(() => demoSnapshot.charts));

  return {
    collectedAt: new Date().toISOString(),
    provider,
    system,
    models,
    profiles,
    fanCurves,
    benchmarks,
    audit,
    logs,
    charts,
  };
}

export async function persistSnapshot(snapshot: DashboardSnapshot): Promise<void> {
  if (!isLiveRuntime()) return;

  const capturedAt = new Date(snapshot.collectedAt);
  const samples = [
    ["gpu_temp_edge", "edge", snapshot.system.gpuTempEdgeC],
    ["gpu_temp_junction", "junction", snapshot.system.gpuTempJunctionC],
    ["gpu_temp_memory", "memory", snapshot.system.gpuTempMemoryC],
    ["gpu_power_w", "power", snapshot.system.gpuPowerW],
    ["gpu_usage", "usage", snapshot.system.gpuUsage],
    [
      "vram_used",
      "used",
      snapshot.system.vramUsedBytes !== null && snapshot.system.vramUsedBytes !== undefined
        ? snapshot.system.vramUsedBytes / 1024 / 1024 / 1024
        : null,
    ],
    [
      "vram_total",
      "total",
      snapshot.system.vramTotalBytes !== null && snapshot.system.vramTotalBytes !== undefined
        ? snapshot.system.vramTotalBytes / 1024 / 1024 / 1024
        : null,
    ],
    [
      "vram_free",
      "free",
      snapshot.system.vramUsedBytes !== null && snapshot.system.vramTotalBytes !== null
        ? (snapshot.system.vramTotalBytes - snapshot.system.vramUsedBytes) / 1024 / 1024 / 1024
        : null,
    ],
    ["cpu_usage", "cpu", snapshot.system.cpuUsage],
    ["ram_used", "ram", snapshot.system.ramUsedBytes / 1024 / 1024 / 1024],
    ["disk_used", "disk", snapshot.system.diskUsedBytes / 1024 / 1024 / 1024],
    ["disk_free", "disk", snapshot.system.diskFreeBytes / 1024 / 1024 / 1024],
    ["fan_pwm", "pwm", snapshot.system.fanPwm],
    ["fan_rpm", "rpm", snapshot.system.fanRpm],
    ["tokens_per_second", "tokens", snapshot.provider.tokensPerSecond],
  ] as const;

  for (const [kind, series, value] of samples) {
    if (value === null || value === undefined || Number.isNaN(value)) continue;
    await prisma.metricSample.create({
      data: {
        kind,
        series,
        value,
        unit:
          kind.startsWith("gpu_temp")
            ? "C"
            : kind === "gpu_power_w"
              ? "W"
              : kind === "gpu_usage" || kind === "cpu_usage"
              ? "%"
            : kind === "fan_pwm"
                ? "pwm"
                : kind === "fan_rpm"
                  ? "rpm"
                  : kind === "tokens_per_second"
                    ? "tok/s"
                    : "GB",
        capturedAt,
      },
    });
  }

  await prisma.providerState.create({
    data: {
      status: snapshot.provider.status,
      model: snapshot.provider.model,
      activeRequests: snapshot.provider.activeRequests,
      promptTokens: snapshot.provider.promptTokens,
      completionTokens: snapshot.provider.completionTokens,
      tokensPerSecond: snapshot.provider.tokensPerSecond,
      providerUrl: snapshot.provider.providerUrl,
      lastError: snapshot.provider.lastError ?? null,
      capturedAt,
    },
  });
}

export async function persistLiveTelemetry(telemetry: LiveTelemetry): Promise<void> {
  const snapshot: DashboardSnapshot = {
    ...demoSnapshot,
    collectedAt: telemetry.collectedAt,
    provider: telemetry.provider,
    system: telemetry.system,
  };
  await persistSnapshot(snapshot);
}

export async function pruneTelemetry(): Promise<void> {
  await aggregateTelemetry();
  const rawCutoff = new Date(Date.now() - 6 * 60 * 60 * 1000);
  const minuteCutoff = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
  const hourCutoff = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000);
  await Promise.all([
    prisma.metricSample.deleteMany({ where: { capturedAt: { lt: rawCutoff } } }),
    prisma.providerState.deleteMany({ where: { capturedAt: { lt: rawCutoff } } }),
    prisma.metricMinute.deleteMany({ where: { bucketAt: { lt: minuteCutoff } } }),
    prisma.metricHour.deleteMany({ where: { bucketAt: { lt: hourCutoff } } }),
  ]);
  await prisma.$executeRawUnsafe("PRAGMA wal_checkpoint(PASSIVE)");
  await prisma.$executeRawUnsafe("PRAGMA optimize");
  await prisma.$executeRawUnsafe("PRAGMA incremental_vacuum(2000)");
}

export async function aggregateTelemetry(): Promise<void> {
  await prisma.$executeRawUnsafe(`
    INSERT OR REPLACE INTO MetricMinute(id,kind,series,average,minimum,maximum,samples,unit,bucketAt)
    SELECT lower(hex(randomblob(16))), kind, series, avg(value), min(value), max(value), count(*), unit,
           strftime('%Y-%m-%dT%H:%M:00.000Z', capturedAt)
    FROM MetricSample
    WHERE datetime(capturedAt) >= datetime('now', '-7 days')
    GROUP BY kind, series, unit, strftime('%Y-%m-%dT%H:%M', capturedAt)
  `);
  await prisma.$executeRawUnsafe(`
    INSERT OR REPLACE INTO MetricHour(id,kind,series,average,minimum,maximum,samples,unit,bucketAt)
    SELECT lower(hex(randomblob(16))), kind, series, avg(value), min(value), max(value), count(*), unit,
           strftime('%Y-%m-%dT%H:00:00.000Z', capturedAt)
    FROM MetricSample
    WHERE datetime(capturedAt) >= datetime('now', '-365 days')
    GROUP BY kind, series, unit, strftime('%Y-%m-%dT%H', capturedAt)
  `);
}
