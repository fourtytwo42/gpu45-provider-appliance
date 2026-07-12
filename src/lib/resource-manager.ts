import { getConfig } from "./config";

export type ResourceOwner = {
  leaseId: string;
  jobId: string;
  kind: string;
  priority: number;
  preemptible: boolean;
  resumePolicy: string;
  acquiredAt: string;
  heartbeatAt: string;
};

export type ResourceQueueItem = {
  requestId: string;
  jobId: string;
  kind: string;
  priority: number;
  preemptible: boolean;
  resumePolicy: string;
  requestedAt: string;
  waitReason: string;
};

export type ResourceState = {
  status: "ready" | "busy" | "offline";
  owner: ResourceOwner | null;
  queue: ResourceQueueItem[];
  suspended: ResourceQueueItem[];
  vram: { usedBytes: number | null; totalBytes: number | null; freeBytes: number | null };
  recovery: { reclaimedLeases: number; lastEvent: string | null };
  transition: { status: "releasing" | "restoring" | "starting"; startedAt: string } | null;
  services: Record<string, "active" | "activating" | "deactivating" | "inactive" | "failed" | "unknown">;
};

export async function getResourceState(): Promise<ResourceState> {
  const cfg = getConfig();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2_500);
  try {
    const response = await fetch(`${cfg.resourceManagerUrl}/v1/state`, {
      cache: "no-store",
      signal: controller.signal,
      headers: cfg.resourceManagerToken ? { Authorization: `Bearer ${cfg.resourceManagerToken}` } : {},
    });
    if (!response.ok) throw new Error(`resource manager returned ${response.status}`);
    return await response.json() as ResourceState;
  } catch {
    return {
      status: "offline",
      owner: null,
      queue: [],
      suspended: [],
      vram: { usedBytes: null, totalBytes: null, freeBytes: null },
      recovery: { reclaimedLeases: 0, lastEvent: null },
      transition: null,
      services: {},
    };
  } finally {
    clearTimeout(timer);
  }
}
