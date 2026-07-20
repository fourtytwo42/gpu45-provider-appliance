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
  provider?: {
    profileName: string;
    servedAlias: string | null;
    backend: string | null;
    contextTokens: number | null;
  } | null;
  services: Record<string, "active" | "activating" | "deactivating" | "inactive" | "failed" | "unknown">;
  workers: Record<string, ResourceWorkerState>;
};

export type ResourceWorkerState = {
  kind: string;
  service: string;
  workerStatus: "active" | "activating" | "deactivating" | "inactive" | "failed" | "unknown";
  loadedModel: string | null;
  idleDeadline: string | null;
  memoryBytes: number | null;
  heartbeatAt: string | null;
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
      provider: null,
      services: {},
      workers: {},
    };
  } finally {
    clearTimeout(timer);
  }
}

export async function touchResourceWorker(kind: "tts" | "image" | "video" | "whisper"): Promise<ResourceWorkerState> {
  const cfg = getConfig();
  const response = await fetch(`${cfg.resourceManagerUrl}/v1/workers/${kind}/touch`, {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(cfg.resourceManagerToken ? { Authorization: `Bearer ${cfg.resourceManagerToken}` } : {}),
    },
    body: "{}",
  });
  if (!response.ok) throw new Error(`Could not start ${kind} worker: ${response.status}`);
  return await response.json() as ResourceWorkerState;
}
