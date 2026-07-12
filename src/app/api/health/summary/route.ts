import { getOperationalJobsSummary, getPersistedOperationalTelemetry } from "@/lib/operational-state";
import { recordRequest } from "@/lib/observability";
import { getApplianceVersion } from "@/lib/version";
import { getResourceState } from "@/lib/resource-manager";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  const startedAt = performance.now();
  let ok = false;
  try {
    const resourceState = await getResourceState();
    const [snapshot, jobs] = await Promise.all([
      getPersistedOperationalTelemetry(resourceState),
      getOperationalJobsSummary(resourceState),
    ]);
    const collectedAt = new Date(snapshot.collectedAt);
    const telemetryFresh = Date.now() - collectedAt.getTime() < 45_000;
    const providerHealthy = snapshot.provider.status !== "failed";
    const status = telemetryFresh && providerHealthy && resourceState.status !== "offline" ? "ok" : "degraded";

    return Response.json({
      status,
      version: getApplianceVersion(),
      collectedAt: snapshot.collectedAt,
      provider: {
        status: snapshot.provider.status,
        model: snapshot.provider.model,
        activeRequests: snapshot.provider.activeRequests,
        lastError: snapshot.provider.lastError,
        processStatus: snapshot.provider.processStatus,
        proxyReady: snapshot.provider.proxyReady,
        backendReady: snapshot.provider.backendReady,
        resourceOwner: snapshot.provider.resourceOwner,
        transition: snapshot.provider.transition,
      },
      resources: {
        gpuUsage: snapshot.system.gpuUsage,
        gpuTempJunctionC: snapshot.system.gpuTempJunctionC,
        vramUsedBytes: snapshot.system.vramUsedBytes,
        vramTotalBytes: snapshot.system.vramTotalBytes,
        diskFreeBytes: snapshot.system.diskFreeBytes,
        manager: resourceState,
      },
      jobs,
      checks: {
        telemetryFresh,
        providerHealthy,
        providerProxy: snapshot.provider.proxyReady,
        providerBackend: snapshot.provider.backendReady,
        providerProcess: snapshot.provider.processStatus,
        database: true,
        resourceManager: resourceState.status !== "offline",
      },
    }, { headers: { "Cache-Control": "no-store", "Server-Timing": `health;dur=${(performance.now() - startedAt).toFixed(1)}` } });
  } catch (error) {
    ok = true;
    return Response.json({
      status: "error",
      version: getApplianceVersion(),
      error: error instanceof Error ? error.message : "Health collection failed.",
    }, { status: 503, headers: { "Cache-Control": "no-store" } });
  } finally {
    recordRequest("/api/health/summary", performance.now() - startedAt, ok);
  }
}
