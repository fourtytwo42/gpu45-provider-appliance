import { prisma } from "./db";
import { demoSnapshot } from "./demo-data";
import type { JobsSummary, UnifiedJob } from "./jobs";
import type { ResourceState } from "./resource-manager";
import type { LiveTelemetry, MetricKind, ProviderProcessStatus, ProviderSnapshot, ProviderStatus, SystemSnapshot } from "./types";

const GIB = 1024 ** 3;
const PROVIDER_STATUSES = new Set<ProviderStatus>(["unloaded", "starting", "ready", "busy", "releasing", "restoring", "failed"]);

function metricValues(samples: Array<{ kind: string; value: number }>): Map<string, number> {
  const latest = new Map<string, number>();
  for (const sample of samples) {
    if (!latest.has(sample.kind)) latest.set(sample.kind, sample.value);
  }
  return latest;
}

function metric(metrics: Map<string, number>, kind: MetricKind): number | null {
  return metrics.get(kind) ?? null;
}

function bytesFromGib(value: number | null): number | null {
  return value === null ? null : value * GIB;
}

function processStatus(resourceState: ResourceState): ProviderProcessStatus {
  return resourceState.services.llm ?? "unknown";
}

export function derivePersistedProviderStatus(resourceState: ResourceState, persistedStatus: string | null, activeRequests: number): ProviderStatus {
  if (resourceState.transition) return resourceState.transition.status;
  if (resourceState.owner?.kind && resourceState.owner.kind !== "llm") return "unloaded";
  const process = processStatus(resourceState);
  if (process === "inactive" || process === "deactivating") return "unloaded";
  if (process === "failed") return "failed";
  if (process === "activating" || resourceState.owner?.kind === "llm") return activeRequests > 0 ? "busy" : "starting";
  if (process === "active") {
    if (activeRequests > 0) return "busy";
    if (persistedStatus && PROVIDER_STATUSES.has(persistedStatus as ProviderStatus) && persistedStatus !== "unloaded") {
      return persistedStatus as ProviderStatus;
    }
    return "starting";
  }
  return persistedStatus && PROVIDER_STATUSES.has(persistedStatus as ProviderStatus)
    ? persistedStatus as ProviderStatus
    : "unloaded";
}

export async function getPersistedOperationalTelemetry(resourceState: ResourceState): Promise<LiveTelemetry> {
  const [providerState, samples] = await Promise.all([
    prisma.providerState.findFirst({ orderBy: { capturedAt: "desc" } }),
    prisma.metricSample.findMany({ orderBy: { capturedAt: "desc" }, take: 128 }),
  ]);
  const values = metricValues(samples);
  const vramUsedBytes = bytesFromGib(metric(values, "vram_used")) ?? resourceState.vram.usedBytes;
  const vramTotalBytes = bytesFromGib(metric(values, "vram_total")) ?? resourceState.vram.totalBytes;
  const ramUsedBytes = bytesFromGib(metric(values, "ram_used")) ?? demoSnapshot.system.ramUsedBytes;
  const ramTotalBytes = bytesFromGib(metric(values, "ram_total")) ?? demoSnapshot.system.ramTotalBytes;
  const diskUsedBytes = bytesFromGib(metric(values, "disk_used")) ?? demoSnapshot.system.diskUsedBytes;
  const diskFreeBytes = bytesFromGib(metric(values, "disk_free")) ?? demoSnapshot.system.diskFreeBytes;
  const diskTotalBytes = bytesFromGib(metric(values, "disk_total")) ?? diskUsedBytes + diskFreeBytes;
  const activeRequests = providerState?.activeRequests ?? 0;
  const status = derivePersistedProviderStatus(resourceState, providerState?.status ?? null, activeRequests);
  const process = processStatus(resourceState);

  const provider: ProviderSnapshot = {
    status,
    model: providerState?.model ?? "unknown",
    providerUrl: providerState?.providerUrl ?? demoSnapshot.provider.providerUrl,
    activeRequests,
    promptTokens: providerState?.promptTokens ?? 0,
    completionTokens: providerState?.completionTokens ?? 0,
    tokensPerSecond: providerState?.tokensPerSecond ?? 0,
    metrics: {},
    lastError: status === "failed" ? providerState?.lastError ?? "The provider process failed." : null,
    processStatus: process,
    proxyReady: status !== "failed",
    backendReady: process === "active" && (status === "ready" || status === "busy"),
    resourceOwner: resourceState.owner?.kind ?? null,
    transition: resourceState.transition?.status ?? null,
  };
  const system: SystemSnapshot = {
    cpuUsage: metric(values, "cpu_usage") ?? 0,
    loadAverage: [0, 0, 0],
    ramUsedBytes,
    ramTotalBytes,
    diskUsedBytes,
    diskFreeBytes,
    diskTotalBytes,
    gpuTempEdgeC: metric(values, "gpu_temp_edge"),
    gpuTempJunctionC: metric(values, "gpu_temp_junction"),
    gpuTempMemoryC: metric(values, "gpu_temp_memory"),
    gpuPowerW: metric(values, "gpu_power_w"),
    gpuUsage: metric(values, "gpu_usage"),
    vramUsedBytes,
    vramTotalBytes,
    fanPwm: metric(values, "fan_pwm"),
    fanRpm: metric(values, "fan_rpm"),
    fanLabel: null,
  };
  const collectedAt = [providerState?.capturedAt, samples[0]?.capturedAt]
    .filter((value): value is Date => Boolean(value))
    .sort((left, right) => right.getTime() - left.getTime())[0]?.toISOString() ?? new Date(0).toISOString();
  return { collectedAt, provider, system };
}

export async function getOperationalJobsSummary(resourceState: ResourceState): Promise<JobsSummary> {
  const downloadGroups = await prisma.downloadJob.groupBy({ by: ["status"], _count: { _all: true } }).catch(() => []);
  const downloads = new Map(downloadGroups.map((group) => [group.status, group._count._all]));
  const resourceActive = resourceState.owner ? 1 : 0;
  const resourceQueued = resourceState.queue.length + resourceState.suspended.length;
  const downloadActive = downloads.get("downloading") ?? 0;
  const downloadQueued = downloads.get("queued") ?? 0;
  const failed = downloads.get("failed") ?? 0;
  const completed = downloads.get("completed") ?? 0;
  return {
    total: resourceActive + resourceQueued + downloadActive + downloadQueued + failed + completed,
    active: resourceActive + resourceQueued + downloadActive + downloadQueued,
    queued: resourceQueued + downloadQueued,
    failed,
    completed,
  };
}

export async function getOperationalJobs(resourceState: ResourceState): Promise<{ jobs: UnifiedJob[]; summary: JobsSummary }> {
  const jobs: UnifiedJob[] = [];
  if (resourceState.owner) {
    jobs.push({
      id: `resource:${resourceState.owner.leaseId}`,
      sourceId: resourceState.owner.jobId,
      kind: resourceState.owner.kind as UnifiedJob["kind"],
      title: `${resourceState.owner.kind.replaceAll("-", " ")} job`,
      subtitle: resourceState.owner.jobId,
      status: "running",
      displayStatus: "Running",
      stage: "GPU allocated",
      createdAt: resourceState.owner.acquiredAt,
      updatedAt: resourceState.owner.heartbeatAt,
      resourceOwner: resourceState.owner.kind,
      preemptible: resourceState.owner.preemptible,
      resumePolicy: resourceState.owner.resumePolicy,
      actions: [],
      availableActions: [],
    });
  }
  for (const item of resourceState.queue) {
    jobs.push({
      id: `resource:${item.requestId}`,
      sourceId: item.jobId,
      kind: item.kind as UnifiedJob["kind"],
      title: `${item.kind.replaceAll("-", " ")} job`,
      subtitle: item.jobId,
      status: "queued",
      displayStatus: "Waiting for GPU",
      stage: "Queued",
      createdAt: item.requestedAt,
      updatedAt: item.requestedAt,
      resourceOwner: resourceState.owner?.kind ?? null,
      waitReason: item.waitReason,
      preemptible: item.preemptible,
      resumePolicy: item.resumePolicy,
      actions: [],
      availableActions: [],
    });
  }
  for (const item of resourceState.suspended) {
    jobs.push({
      id: `resource:${item.requestId}`,
      sourceId: item.jobId,
      kind: item.kind as UnifiedJob["kind"],
      title: `${item.kind.replaceAll("-", " ")} job`,
      subtitle: item.jobId,
      status: "paused",
      displayStatus: "Paused",
      stage: "Paused at a safe boundary",
      createdAt: item.requestedAt,
      updatedAt: item.requestedAt,
      resourceOwner: resourceState.owner?.kind ?? null,
      waitReason: item.waitReason,
      preemptible: item.preemptible,
      resumePolicy: item.resumePolicy,
      actions: [],
      availableActions: [],
    });
  }
  const downloads = await prisma.downloadJob.findMany({
    where: { status: { in: ["queued", "downloading", "failed"] } },
    orderBy: { updatedAt: "desc" },
    take: 20,
  }).catch(() => []);
  for (const job of downloads) {
    const status = job.status === "downloading" ? "running" : job.status as UnifiedJob["status"];
    jobs.push({
      id: `download:${job.id}`,
      sourceId: job.id,
      kind: "download",
      title: job.fileName,
      subtitle: job.repoId,
      status,
      displayStatus: status === "running" ? "Downloading" : status.charAt(0).toUpperCase() + status.slice(1),
      progressPercent: Number(job.totalBytes) > 0 ? Math.round((Number(job.bytesDownloaded) / Number(job.totalBytes)) * 1000) / 10 : null,
      createdAt: job.createdAt.toISOString(),
      updatedAt: job.updatedAt.toISOString(),
      error: job.error,
      technicalError: job.error,
      userMessage: job.error,
      actions: status === "failed" ? ["delete"] : [],
      availableActions: status === "failed" ? ["delete"] : [],
    });
  }
  const summary = jobs.reduce<JobsSummary>((value, job) => {
    value.total += 1;
    if (["running", "queued", "paused"].includes(job.status)) value.active += 1;
    if (job.status === "queued") value.queued += 1;
    if (job.status === "failed") value.failed += 1;
    if (job.status === "completed") value.completed += 1;
    return value;
  }, { total: 0, active: 0, queued: 0, failed: 0, completed: 0 });
  return { jobs, summary };
}
