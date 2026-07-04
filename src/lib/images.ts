import { getConfig } from "./config";

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
  error?: string;
};

function imageUrl(path: string): string {
  return `${getConfig().imageUrl.replace(/\/$/, "")}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(imageUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export async function getImageSnapshot(): Promise<ImageSnapshot> {
  const serviceUrl = getConfig().imageUrl;
  try {
    const [health, jobs] = await Promise.all([
      fetchJson<{ status: string; profiles?: ImageProfile[] }>("/health"),
      fetchJson<ImageJob[]>("/jobs"),
    ]);
    return {
      healthy: health.status === "ok",
      serviceUrl,
      profiles: health.profiles ?? [],
      jobs,
    };
  } catch (error) {
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
  const response = await fetch(imageUrl(`/jobs/${encodeURIComponent(id)}/image`), { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return response;
}

export function imageOutputUrl(id: string): string {
  return `/api/images/output?id=${encodeURIComponent(id)}`;
}
