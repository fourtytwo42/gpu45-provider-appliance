import { z } from "zod";
import { collectProviderSnapshot, collectSystemSnapshot } from "./collectors";
import { activateModel } from "./control";
import { getConfig, isLiveRuntime } from "./config";
import { prisma } from "./db";
import { readHostText } from "./proxmox";
import type { BenchmarkRun } from "./types";

export const DEFAULT_BENCHMARK_PROMPT =
  "Run a sustained local LLM throughput benchmark. Write a detailed technical analysis of GPU inference stability, thermal headroom, VRAM pressure, batching, context cache behavior, and operational monitoring. Keep writing until the response budget is nearly exhausted.";

export const benchmarkOptionsSchema = z.object({
  model: z.string().min(1).max(200),
  modelPath: z.string().min(1).max(2000).optional(),
  prompt: z.string().min(1).max(100_000).default(DEFAULT_BENCHMARK_PROMPT),
  maxOutputTokens: z.coerce.number().int().min(16).max(4096).default(2048),
  temperature: z.coerce.number().min(0).max(2).default(0),
  repetitions: z.coerce.number().int().min(1).max(5).default(2),
  warmup: z.coerce.boolean().default(false),
});

export type BenchmarkOptions = z.infer<typeof benchmarkOptionsSchema>;
export type BenchmarkJobStatus = "queued" | "loading-model" | "running" | "completed" | "failed";
export type BenchmarkProgressSample = {
  timestamp: string;
  elapsedMs: number;
  runIndex: number;
  phase: BenchmarkJobStatus;
  gpuTempC: number | null;
  gpuUsage: number | null;
  vramUsedBytes: number | null;
  gpuPowerW: number | null;
  tokensPerSecond: number | null;
};

export type BenchmarkJob = {
  id: string;
  status: BenchmarkJobStatus;
  model: string;
  modelPath?: string;
  activeRun: number;
  totalRuns: number;
  startedAt: string;
  updatedAt: string;
  completedAt?: string;
  runId?: string;
  error?: string;
  message: string;
  samples: BenchmarkProgressSample[];
  partialRuns: Array<{
    runIndex: number;
    durationMs: number;
    promptTokens: number;
    completionTokens: number;
    generationTokensPerSecond: number;
    promptTokensPerSecond: number;
    peakGpuTempC: number | null;
    peakVramBytes: number | null;
  }>;
};

type ChatResult = {
  usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
  timings?: { prompt_per_second?: number; predicted_per_second?: number };
};

type ProgressReporter = (sample: BenchmarkProgressSample) => void;

const benchmarkJobs = new Map<string, BenchmarkJob>();

function createId(): string {
  return `bench_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

function touch(job: BenchmarkJob, patch: Partial<BenchmarkJob>): void {
  Object.assign(job, patch, { updatedAt: new Date().toISOString() });
}

function publicJob(job: BenchmarkJob): BenchmarkJob {
  return {
    ...job,
    samples: job.samples.slice(-120),
    partialRuns: [...job.partialRuns],
  };
}

type ProviderProfileRef = {
  name?: string;
  modelPath?: string;
};

async function readProviderProfile(): Promise<ProviderProfileRef | null> {
  const text = await readHostText(getConfig().providerProfilePath);
  if (!text) return null;
  try {
    return JSON.parse(text) as ProviderProfileRef;
  } catch {
    return null;
  }
}

async function waitForProviderModel(model: string, timeoutMs = 180_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastModel = "";
  while (Date.now() < deadline) {
    const [provider, profile] = await Promise.all([
      collectProviderSnapshot().catch(() => null),
      readProviderProfile().catch(() => null),
    ]);
    if (provider?.model) {
      lastModel = provider.model;
      if (provider.model === model) return;
    }
    if (
      profile?.name === model
      && provider
      && (provider.status === "ready" || provider.status === "busy")
    ) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 2500));
  }
  throw new Error(`Timed out waiting for provider to load ${model}. Last reported model: ${lastModel || "unknown"}`);
}

async function ensureBenchmarkModelLoaded(modelPath: string): Promise<string> {
  const profile = await readProviderProfile();
  const provider = await collectProviderSnapshot().catch(() => null);
  if (profile?.modelPath === modelPath && profile.name && provider?.model === profile.name) {
    return profile.name;
  }

  const activation = await activateModel(modelPath);
  if (!activation.ok) throw new Error(activation.message);
  const nextProfile = await readProviderProfile();
  if (!nextProfile?.name) throw new Error("Provider profile was not written with a model name.");
  await waitForProviderModel(nextProfile.name);
  return nextProfile.name;
}

async function executeOnce(
  options: BenchmarkOptions,
  runIndex: number,
  report?: ProgressReporter,
): Promise<{ json: ChatResult; durationMs: number; peakTemp: number | null; peakVram: number | null }> {
  let running = true;
  let peakTemp: number | null = null;
  let peakVram: number | null = null;
  const started = Date.now();
  const sampler = (async () => {
    while (running) {
      const [system, provider] = await Promise.all([
        collectSystemSnapshot().catch(() => null),
        collectProviderSnapshot().catch(() => null),
      ]);
      if (system) {
        const temperature = system.gpuTempJunctionC ?? system.gpuTempEdgeC ?? system.gpuTempMemoryC;
        if (temperature !== null) peakTemp = Math.max(peakTemp ?? temperature, temperature);
        if (system.vramUsedBytes !== null) peakVram = Math.max(peakVram ?? system.vramUsedBytes, system.vramUsedBytes);
        report?.({
          timestamp: new Date().toISOString(),
          elapsedMs: Date.now() - started,
          runIndex,
          phase: "running",
          gpuTempC: temperature,
          gpuUsage: system.gpuUsage,
          vramUsedBytes: system.vramUsedBytes,
          gpuPowerW: system.gpuPowerW,
          tokensPerSecond: provider?.tokensPerSecond ?? null,
        });
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  })();
  try {
    const response = await fetch(`${getConfig().backendUrl}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: options.model,
        messages: [{ role: "user", content: options.prompt }],
        max_tokens: options.maxOutputTokens,
        temperature: options.temperature,
        stream: false,
      }),
    });
    if (!response.ok) throw new Error(`Provider returned ${response.status}: ${(await response.text()).slice(0, 300)}`);
    return { json: await response.json() as ChatResult, durationMs: Date.now() - started, peakTemp, peakVram };
  } finally {
    running = false;
    await sampler;
  }
}

export async function runConfiguredBenchmark(input: unknown, onProgress?: (job: { runIndex: number; totalRuns: number; sample?: BenchmarkProgressSample; result?: BenchmarkJob["partialRuns"][number] }) => void): Promise<{ ok: true; runId: string }> {
  if (!isLiveRuntime()) throw new Error("Benchmarks require live mode");
  const options = benchmarkOptionsSchema.parse(input);
  if (options.modelPath) {
    await ensureBenchmarkModelLoaded(options.modelPath);
  } else {
    const provider = await collectProviderSnapshot();
    if (provider.model !== options.model) throw new Error(`Only the loaded model can be benchmarked. Active model: ${provider.model}`);
  }
  if (options.warmup) await executeOnce({ ...options, maxOutputTokens: Math.min(32, options.maxOutputTokens) }, 0);

  let promptTokens = 0;
  let completionTokens = 0;
  let durationMs = 0;
  let promptRate = 0;
  let generationRate = 0;
  let peakTemp: number | null = null;
  let peakVram: number | null = null;
  for (let index = 0; index < options.repetitions; index += 1) {
    const runIndex = index + 1;
    const result = await executeOnce(options, runIndex, (sample) => onProgress?.({ runIndex, totalRuns: options.repetitions, sample }));
    const runPromptTokens = result.json.usage?.prompt_tokens ?? 0;
    const runCompletionTokens = result.json.usage?.completion_tokens ?? 0;
    const runPromptRate = result.json.timings?.prompt_per_second ?? runPromptTokens / Math.max(result.durationMs / 1000, 0.001);
    const runGenerationRate = result.json.timings?.predicted_per_second ?? runCompletionTokens / Math.max(result.durationMs / 1000, 0.001);
    promptTokens += runPromptTokens;
    completionTokens += runCompletionTokens;
    durationMs += result.durationMs;
    promptRate += runPromptRate;
    generationRate += runGenerationRate;
    if (result.peakTemp !== null) peakTemp = Math.max(peakTemp ?? result.peakTemp, result.peakTemp);
    if (result.peakVram !== null) peakVram = Math.max(peakVram ?? result.peakVram, result.peakVram);
    onProgress?.({
      runIndex,
      totalRuns: options.repetitions,
      result: {
        runIndex,
        durationMs: result.durationMs,
        promptTokens: runPromptTokens,
        completionTokens: runCompletionTokens,
        promptTokensPerSecond: runPromptRate,
        generationTokensPerSecond: runGenerationRate,
        peakGpuTempC: result.peakTemp,
        peakVramBytes: result.peakVram,
      },
    });
  }
  const divisor = options.repetitions;
  const run = await prisma.benchmarkRun.create({
    data: {
      modelName: options.model,
      prompt: options.prompt,
      totalTokens: promptTokens + completionTokens,
      promptTokens,
      completionTokens,
      promptTokensPerSecond: promptRate / divisor,
      generationTokensPerSecond: generationRate / divisor,
      durationMs,
      peakGpuTempC: peakTemp,
      peakVramBytes: peakVram === null ? null : BigInt(Math.round(peakVram)),
      notes: `${options.repetitions} back-to-back run${options.repetitions === 1 ? "" : "s"} at ${options.maxOutputTokens} max output tokens`,
      optionsJson: JSON.stringify(options),
    },
  });
  await prisma.auditLog.create({ data: { action: "benchmark.run", subject: options.model, details: `run=${run.id}` } });
  return { ok: true, runId: run.id };
}

export function startBenchmarkJob(input: unknown): BenchmarkJob {
  const options = benchmarkOptionsSchema.parse(input);
  const job: BenchmarkJob = {
    id: createId(),
    status: options.modelPath ? "loading-model" : "queued",
    model: options.model,
    modelPath: options.modelPath,
    activeRun: 0,
    totalRuns: options.repetitions,
    startedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    message: options.modelPath ? "Preparing selected model" : "Queued",
    samples: [],
    partialRuns: [],
  };
  benchmarkJobs.set(job.id, job);
  void runConfiguredBenchmark(options, ({ runIndex, totalRuns, sample, result }) => {
    touch(job, {
      status: "running",
      activeRun: runIndex,
      totalRuns,
      message: result ? `Run ${runIndex} completed` : `Run ${runIndex} of ${totalRuns} in progress`,
    });
    if (sample) job.samples.push(sample);
    if (result) job.partialRuns.push(result);
  }).then(({ runId }) => {
    touch(job, {
      status: "completed",
      completedAt: new Date().toISOString(),
      runId,
      activeRun: job.totalRuns,
      message: "Benchmark completed",
    });
  }).catch((error) => {
    touch(job, {
      status: "failed",
      completedAt: new Date().toISOString(),
      error: error instanceof Error ? error.message : "Benchmark failed",
      message: "Benchmark failed",
    });
  });
  return publicJob(job);
}

export function getBenchmarkJob(id: string): BenchmarkJob | null {
  const job = benchmarkJobs.get(id);
  return job ? publicJob(job) : null;
}

export async function listBenchmarkRuns(limit = 200): Promise<BenchmarkRun[]> {
  const runs = await prisma.benchmarkRun.findMany({
    orderBy: { createdAt: "desc" },
    take: Math.max(1, Math.min(limit, 500)),
  });
  return runs.map((run) => ({
    ...run,
    peakVramBytes: run.peakVramBytes === null ? null : Number(run.peakVramBytes),
    createdAt: run.createdAt.toISOString(),
  }));
}
