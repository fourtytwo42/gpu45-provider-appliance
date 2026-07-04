import { getConfig } from "./config";

export type VideoJobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type VideoJob = {
  id: string;
  profile?: string;
  profile_name?: string;
  prompt: string;
  negative_prompt?: string;
  size: string;
  steps: number;
  duration_seconds?: number;
  frame_num?: number;
  seed: number;
  status: VideoJobStatus;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  output_path?: string | null;
  error?: string | null;
  progress_percent?: number;
  progress_label?: string;
  progress_stage?: string;
};

export type VideoProfile = {
  id: string;
  name: string;
  description: string;
  repo: string;
  model_dir: string;
  ready: boolean;
};

export type VideoSnapshot = {
  healthy: boolean;
  serviceUrl: string;
  modelReady: boolean;
  profiles: VideoProfile[];
  jobs: VideoJob[];
  error?: string;
};

function videoUrl(path: string): string {
  return `${getConfig().videoUrl.replace(/\/$/, "")}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(videoUrl(path), {
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

export async function getVideoSnapshot(): Promise<VideoSnapshot> {
  const serviceUrl = getConfig().videoUrl;
  try {
    const [health, jobs] = await Promise.all([
      fetchJson<{ status: string; model_ready: boolean; profiles?: VideoProfile[] }>("/health"),
      fetchJson<VideoJob[]>("/jobs"),
    ]);
    return { healthy: health.status === "ok", serviceUrl, modelReady: health.model_ready, profiles: health.profiles ?? [], jobs };
  } catch (error) {
    return {
      healthy: false,
      serviceUrl,
      modelReady: false,
      profiles: [],
      jobs: [],
      error: error instanceof Error ? error.message : "Video service unavailable",
    };
  }
}

export async function createVideoJob(payload: Record<string, unknown>): Promise<VideoJob> {
  return await fetchJson<VideoJob>("/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function startVideoModelDownload(profile = "wan22-ti2v-5b"): Promise<Record<string, unknown>> {
  return await fetchJson<Record<string, unknown>>(`/model/download?profile=${encodeURIComponent(profile)}`, { method: "POST" });
}

export async function cancelVideoJob(id: string): Promise<Record<string, unknown>> {
  return await fetchJson<Record<string, unknown>>(`/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

export async function deleteVideoJob(id: string): Promise<Record<string, unknown>> {
  return await fetchJson<Record<string, unknown>>(`/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function videoOutputUrl(id: string): string {
  return `/api/video/output?id=${encodeURIComponent(id)}`;
}
