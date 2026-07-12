import { getOperationalJobsSummary, getPersistedOperationalTelemetry } from "@/lib/operational-state";
import { prometheusLabel, requestMetrics } from "@/lib/observability";
import { getResourceState } from "@/lib/resource-manager";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function metric(name: string, help: string, value: number | null | undefined, labels = ""): string[] {
  if (value === null || value === undefined || !Number.isFinite(value)) return [];
  return [`# HELP ${name} ${help}`, `# TYPE ${name} gauge`, `${name}${labels} ${value}`];
}

export async function GET(): Promise<Response> {
  const resources = await getResourceState();
  const [telemetry, jobs] = await Promise.all([
    getPersistedOperationalTelemetry(resources),
    getOperationalJobsSummary(resources),
  ]);
  const lines = [
    ...metric("gpu45_gpu_usage_percent", "Current GPU utilization.", telemetry.system.gpuUsage),
    ...metric("gpu45_gpu_junction_temperature_celsius", "Current GPU junction temperature.", telemetry.system.gpuTempJunctionC),
    ...metric("gpu45_gpu_power_watts", "Current GPU board power.", telemetry.system.gpuPowerW),
    ...metric("gpu45_vram_used_bytes", "Current GPU VRAM allocation.", telemetry.system.vramUsedBytes),
    ...metric("gpu45_vram_total_bytes", "Total GPU VRAM.", telemetry.system.vramTotalBytes),
    ...metric("gpu45_disk_free_bytes", "Free appliance storage.", telemetry.system.diskFreeBytes),
    ...metric("gpu45_jobs_active", "Active and paused appliance jobs.", jobs.active),
    ...metric("gpu45_jobs_queued", "Queued appliance jobs.", jobs.queued),
    ...metric("gpu45_resource_queue_depth", "GPU resource queue depth.", resources.queue.length + resources.suspended.length),
    ...metric("gpu45_provider_ready", "Whether the provider can accept or start an LLM request.", telemetry.provider.status === "failed" ? 0 : 1),
  ];
  for (const [kind, worker] of Object.entries(resources.workers)) {
    const labels = `{worker="${prometheusLabel(kind)}"}`;
    lines.push(...metric("gpu45_worker_active", "Whether a heavy worker process is active.", worker.workerStatus === "active" ? 1 : 0, labels));
    lines.push(...metric("gpu45_worker_memory_bytes", "Heavy worker resident memory.", worker.memoryBytes, labels));
  }
  for (const request of requestMetrics()) {
    const labels = `{route="${prometheusLabel(request.route)}"}`;
    lines.push(...metric("gpu45_http_requests_total", "Observed API requests since web process start.", request.count, labels));
    lines.push(...metric("gpu45_http_request_failures_total", "Observed API failures since web process start.", request.failures, labels));
    lines.push(...metric("gpu45_http_request_duration_milliseconds_total", "Accumulated API request duration.", request.durationMs, labels));
  }
  return new Response(`${lines.join("\n")}\n`, {
    headers: { "Content-Type": "text/plain; version=0.0.4; charset=utf-8", "Cache-Control": "no-store" },
  });
}
