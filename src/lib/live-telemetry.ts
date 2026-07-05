import os from "node:os";
import { getConfig, isLiveRuntime } from "./config";
import { runBash, shQuote } from "./command";
import { demoSnapshot } from "./demo-data";
import { parsePrometheusSample } from "./parsers";
import type { LiveTelemetry, ProviderSnapshot, SystemSnapshot } from "./types";

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

async function readText(filePath: string): Promise<string | null> {
  return runBash(`cat ${shQuote(filePath)}`).catch(() => null);
}

async function readJson<T>(filePath: string): Promise<T | null> {
  const text = await readText(filePath);
  if (!text) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

async function readNumber(filePath: string, scale = 1): Promise<number | null> {
  const text = await readText(filePath);
  if (!text) return null;
  const value = Number(text.trim());
  return Number.isFinite(value) ? value / scale : null;
}

async function listDirectories(rootPath: string): Promise<string[]> {
  const text = await runBash(`find ${shQuote(rootPath)} -mindepth 1 -maxdepth 1 -type d -printf '%f\n'`).catch(() => "");
  return text.split(/\r?\n/).map((entry) => entry.trim()).filter(Boolean);
}

async function resolveAmdgpuHwmonPath(): Promise<string> {
  const cfg = getConfig();
  const configuredName = await readText(`${cfg.gpuHwmonPath}/name`);
  if (configuredName?.trim().toLowerCase() === "amdgpu") {
    return cfg.gpuHwmonPath;
  }

  for (const root of [`${cfg.gpuDevicePath}/hwmon`, "/sys/class/hwmon"]) {
    const entries = await listDirectories(root);
    for (const entry of entries) {
      const candidate = `${root}/${entry}`;
      const name = await readText(`${candidate}/name`);
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

export async function collectLiveProviderSnapshot(): Promise<ProviderSnapshot> {
  const cfg = getConfig();
  const [backendModelsResponse, proxyModelsResponse, metricsText] = await Promise.all([
    fetch(`${cfg.backendUrl}/v1/models`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`backend model probe failed: ${response.status}`);
        return response.json();
      })
      .catch(() => null),
    fetch(`${cfg.providerUrl}/v1/models`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(`model probe failed: ${response.status}`);
        return response.json();
      })
      .catch(() => null),
    fetch(`${cfg.providerUrl}/metrics`, { cache: "no-store" }).then(async (response) => {
      if (!response.ok) return "";
      return response.text();
    }),
  ]);

  const model = extractModelId(backendModelsResponse) ?? extractModelId(proxyModelsResponse) ?? "unknown";
  const metrics = parsePrometheusSample(metricsText, [
    "llamacpp:requests_processing",
    "llamacpp:prompt_tokens_total",
    "llamacpp:tokens_predicted_total",
    "llamacpp:prompt_tokens_seconds",
    "llamacpp:predicted_tokens_seconds",
  ]);

  const requestsProcessing = metrics["llamacpp:requests_processing"] ?? 0;
  const promptTokens = metrics["llamacpp:prompt_tokens_total"] ?? 0;
  const completionTokens = metrics["llamacpp:tokens_predicted_total"] ?? 0;
  const tokensPerSecond = metrics["llamacpp:predicted_tokens_seconds"] ?? 0;

  let status: ProviderSnapshot["status"] = "idle";
  if (requestsProcessing > 0) status = "generating";
  if (metricsText.length === 0) status = "loading";

  return {
    status,
    model,
    providerUrl: cfg.providerUrl,
    activeRequests: requestsProcessing,
    promptTokens: Math.round(promptTokens),
    completionTokens: Math.round(completionTokens),
    tokensPerSecond,
    metrics,
    lastError: null,
  };
}

function extractModelId(response: unknown): string | null {
  const dataModel = (response as { data?: Array<{ id?: string; model?: string; name?: string }> } | null)?.data?.[0];
  if (dataModel?.id) return dataModel.id;
  if (dataModel?.model) return dataModel.model;
  if (dataModel?.name) return dataModel.name;
  const modelsModel = (response as { models?: Array<{ id?: string; model?: string; name?: string }> } | null)?.models?.[0];
  if (modelsModel?.id) return modelsModel.id;
  if (modelsModel?.model) return modelsModel.model;
  if (modelsModel?.name) return modelsModel.name;
  return null;
}

export async function collectLiveSystemSnapshot(): Promise<SystemSnapshot> {
  const cfg = getConfig();
  const gpuHwmonPath = await resolveAmdgpuHwmonPath();
  const [
    cpuUsage,
    loadAverage,
    ramSnapshot,
    dfText,
    fan,
    gpuPowerW,
    gpuUsage,
    gpuTempEdgeFromFile,
    gpuTempJunctionFromFile,
    gpuTempMemoryFromFile,
    vramUsedBytes,
    vramTotalBytes,
  ] = await Promise.all([
    collectCpuUsage(),
    collectLoadAverage(),
    collectRamSnapshot(),
    runBash(`df -B1 ${shQuote(cfg.storageRoot)} ${shQuote(cfg.modelRoot)} 2>/dev/null || df -B1 /`).catch(() => ""),
    collectFanSnapshot(),
    readNumber(`${gpuHwmonPath}/power1_average`, 1_000_000),
    readNumber(`${cfg.gpuDevicePath}/gpu_busy_percent`),
    readNumber(`${gpuHwmonPath}/temp1_input`, 1_000),
    readNumber(`${gpuHwmonPath}/temp2_input`, 1_000),
    readNumber(`${gpuHwmonPath}/temp3_input`, 1_000),
    readNumber(`${cfg.gpuDevicePath}/mem_info_vram_used`),
    readNumber(`${cfg.gpuDevicePath}/mem_info_vram_total`),
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
  const remoteStart = await readText("/proc/stat");
  if (remoteStart !== null) {
    await new Promise((resolve) => setTimeout(resolve, 100));
    const remoteEnd = await readText("/proc/stat");
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
  const text = await readText("/proc/loadavg");
  if (text) {
    const values = text.trim().split(/\s+/).slice(0, 3).map((value) => Number(value));
    if (values.length === 3 && values.every((value) => Number.isFinite(value))) {
      return values as [number, number, number];
    }
  }
  return os.loadavg() as [number, number, number];
}

async function collectRamSnapshot(): Promise<{ usedBytes: number; totalBytes: number }> {
  const text = await readText("/proc/meminfo");
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
    (await readJson<FanStateSnapshot>(cfg.fanStatePath).catch(() => null)) ??
    (await readJson<FanStateSnapshot>("/etc/gpu45/fan-state.json").catch(() => null));
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

  if (!(await readText("/usr/local/sbin/gpu45-v620-fan-controller"))) return { pwm: null, rpm: null, label: null };
  const hwmons = await listDirectories("/sys/class/hwmon");
  let fanHwmon: string | null = null;
  for (const entry of hwmons) {
    const candidate = `/sys/class/hwmon/${entry}`;
    const name = await readText(`${candidate}/name`);
    if (isFanControllerHwmonName(name)) {
      fanHwmon = candidate;
      break;
    }
  }
  if (!fanHwmon) {
    for (const entry of hwmons) {
      const candidate = `/sys/class/hwmon/${entry}`;
      const pwmText = await readText(`${candidate}/pwm3`);
      const rpmText = await readText(`${candidate}/fan3_input`);
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
    pwmText = await readText(`${fanHwmon}/${candidate}`);
    if (pwmText !== null) break;
  }
  let rpmText: string | null = null;
  for (const candidate of rpmCandidates) {
    rpmText = await readText(`${fanHwmon}/${candidate}`);
    if (rpmText !== null) break;
  }
  return {
    pwm: pwmText ? Number(pwmText) : null,
    rpm: rpmText ? Number(rpmText) : null,
    label: fanHwmon.split("/").at(-1) ?? fanHwmon,
  };
}

function isFanControllerHwmonName(name: string | null | undefined): boolean {
  const normalized = name?.trim().toLowerCase();
  return normalized === "nct6687" || normalized?.includes("nct6687") || false;
}

export async function collectLiveTelemetry(): Promise<LiveTelemetry> {
  if (!isLiveRuntime()) {
    return { collectedAt: new Date().toISOString(), provider: demoSnapshot.provider, system: demoSnapshot.system };
  }
  const [provider, system] = await Promise.all([
    collectLiveProviderSnapshot().catch((error) => ({
      ...demoSnapshot.provider,
      status: "offline" as const,
      lastError: error instanceof Error ? error.message : "Provider probe failed",
    })),
    collectLiveSystemSnapshot().catch(() => demoSnapshot.system),
  ]);
  return { collectedAt: new Date().toISOString(), provider, system };
}