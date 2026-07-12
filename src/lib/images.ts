import { getConfig } from "./config";
import { managedServiceFetch } from "./managed-service";

export type ImageJobStatus = "queued" | "running" | "completed" | "failed";

export type ImageProfile = {
  id: string;
  name: string;
  description: string;
  repo: string;
  pipeline: string;
  default_steps: number;
  default_width: number;
  default_height: number;
  guidance_scale: number;
  ready: boolean;
  tested?: boolean;
  resolution_options?: Array<{ label: string; width: number; height: number }>;
  step_options?: number[];
  guidance_options?: number[];
  supports_negative_prompt?: boolean;
  recommended?: boolean;
  quality_tier?: string;
  test_summary?: string;
  error?: string | null;
};

export type ImageJob = {
  id: string;
  profile: string;
  profile_name?: string;
  prompt: string;
  negative_prompt?: string | null;
  width: number;
  height: number;
  steps: number;
  guidance_scale: number;
  seed: number;
  status: ImageJobStatus;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
  progress_percent?: number | null;
  progress_label?: string | null;
  progress_step?: number | null;
  progress_total?: number | null;
  eta_seconds?: number | null;
  elapsed_seconds?: number | null;
  output_path?: string | null;
  output_name?: string | null;
  duration_seconds?: number | null;
  peak_vram_mb?: number | null;
  peak_junction_c?: number | null;
  error?: string | null;
};

export type ImageSnapshot = {
  healthy: boolean;
  serviceUrl: string;
  profiles: ImageProfile[];
  jobs: ImageJob[];
  sleeping?: boolean;
  error?: string;
};

let lastSnapshot: ImageSnapshot | null = null;

function imageUrl(path: string): string {
  return `${getConfig().imageUrl.replace(/\/$/, "")}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit, wake = true): Promise<T> {
  const response = await managedServiceFetch("image", imageUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  }, { wake });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export async function getImageSnapshot(): Promise<ImageSnapshot> {
  const serviceUrl = getConfig().imageUrl;
  try {
    const [health, jobs] = await Promise.all([
      fetchJson<{ status: string; profiles?: ImageProfile[] }>("/health", undefined, false),
      fetchJson<ImageJob[]>("/jobs", undefined, false),
    ]);
    const snapshot = {
      healthy: health.status === "ok",
      serviceUrl,
      profiles: health.profiles ?? [],
      jobs,
    };
    lastSnapshot = snapshot;
    return snapshot;
  } catch (error) {
    if (lastSnapshot) return { ...lastSnapshot, sleeping: true };
    try {
      const [health, jobs] = await Promise.all([
        fetchJson<{ status: string; profiles?: ImageProfile[] }>("/health", undefined, true),
        fetchJson<ImageJob[]>("/jobs", undefined, false),
      ]);
      const snapshot = { healthy: health.status === "ok", sleeping: false, serviceUrl, profiles: health.profiles ?? [], jobs };
      lastSnapshot = snapshot;
      return snapshot;
    } catch {
      // Return the original connection failure below.
    }
    return {
      healthy: false,
      serviceUrl,
      profiles: [],
      jobs: [],
      error: error instanceof Error ? error.message : "Image service unavailable",
    };
  }
}

export async function createImageJob(payload: Record<string, unknown>): Promise<ImageJob> {
  return await fetchJson<ImageJob>("/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteImageJob(id: string): Promise<Record<string, unknown>> {
  return await fetchJson<Record<string, unknown>>(`/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function downloadImageModel(profile: string): Promise<Record<string, unknown>> {
  return await fetchJson<Record<string, unknown>>(`/models/${encodeURIComponent(profile)}/download`, { method: "POST" });
}

export async function fetchImageOutput(id: string): Promise<Response> {
  const response = await managedServiceFetch("image", imageUrl(`/jobs/${encodeURIComponent(id)}/image`), undefined, { wake: true });
  if (!response.ok) throw new Error(await response.text());
  return response;
}

export function imageOutputUrl(id: string): string {
  return `/api/images/output?id=${encodeURIComponent(id)}`;
}
