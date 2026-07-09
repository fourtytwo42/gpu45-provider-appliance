import { collectDashboardSnapshot } from "@/lib/collectors";
import { getUnifiedJobs } from "@/lib/jobs";
import { getApplianceVersion } from "@/lib/version";
import { getResourceState } from "@/lib/resource-manager";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  try {
    const [snapshot, jobs, resourceState] = await Promise.all([
      collectDashboardSnapshot(),
      getUnifiedJobs(),
      getResourceState(),
    ]);
    const collectedAt = new Date(snapshot.collectedAt);
    const telemetryFresh = Date.now() - collectedAt.getTime() < 30_000;
    const providerHealthy = !["error", "offline"].includes(snapshot.provider.status);
    const status = telemetryFresh && providerHealthy ? "ok" : "degraded";

    return Response.json({
      status,
      version: getApplianceVersion(),
      collectedAt: snapshot.collectedAt,
      provider: {
        status: snapshot.provider.status,
        model: snapshot.provider.model,
        activeRequests: snapshot.provider.activeRequests,
        lastError: snapshot.provider.lastError,
      },
      resources: {
        gpuUsage: snapshot.system.gpuUsage,
        gpuTempJunctionC: snapshot.system.gpuTempJunctionC,
        vramUsedBytes: snapshot.system.vramUsedBytes,
        vramTotalBytes: snapshot.system.vramTotalBytes,
        diskFreeBytes: snapshot.system.diskFreeBytes,
        manager: resourceState,
      },
      jobs: jobs.summary,
      checks: {
        telemetryFresh,
        providerHealthy,
        database: true,
        resourceManager: resourceState.status !== "offline",
      },
    }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return Response.json({
      status: "error",
      version: getApplianceVersion(),
      error: error instanceof Error ? error.message : "Health collection failed.",
    }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
