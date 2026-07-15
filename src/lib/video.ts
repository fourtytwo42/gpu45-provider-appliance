import { getConfig } from "./config";
import { managedServiceFetch } from "./managed-service";

export type VideoJobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type VideoJob = {
  id: string;
  profile?: string;
  profile_name?: string;
  preset?: "preview" | "balanced";
  preset_name?: string;
  mode?: "t2v" | "i2v";
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
  solver?: string;
};

export type VideoProfile = {
  id: string;
  name: string;
  description: string;
  repo: string;
  model_dir: string;
  ready: boolean;
  assets_ready?: boolean;
  availability_reason?: string | null;
  backend?: string;
  modes?: Array<"t2v" | "i2v">;
  sizes?: string[];
  durations?: number[];
  step_counts?: number[];
  default_steps?: number;
  default_fps?: number;
  expected_vram_gb?: number | null;
  solver?: string;
  recommended_size?: string;
  recommended_steps?: number;
  reference_settings?: string;
  known_limitations?: string[];
  native_audio?: boolean;
  features?: string[];
  output_scale?: number;
  tested_runtime_seconds?: number;
  max_tested_duration_seconds?: number;
  presets?: Record<string, {
    label: string;
    description: string;
    size: string;
    steps: number;
    duration_seconds: number;
    output_scale: number;
    max_tested_duration_seconds: number;
    modes: Array<"t2v" | "i2v">;
  }>;
};

export type VideoSnapshot = {
  healthy: boolean;
  serviceUrl: string;
  modelReady: boolean;
  profiles: VideoProfile[];
  jobs: VideoJob[];
  sleeping?: boolean;
  error?: string;
};

let lastSnapshot: VideoSnapshot | null = null;

function videoUrl(path: string): string {
  return `${getConfig().videoUrl.replace(/\/$/, "")}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit, wake = true): Promise<T> {
  const response = await managedServiceFetch("video", videoUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  }, { wake, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export async function getVideoSnapshot(): Promise<VideoSnapshot> {
  const serviceUrl = getConfig().videoUrl;
  try {
    const [health, jobs] = await Promise.all([
      fetchJson<{ status: string; model_ready: boolean; profiles?: VideoProfile[] }>("/health", undefined, false),
      fetchJson<VideoJob[]>("/jobs", undefined, false),
    ]);
    const snapshot = { healthy: health.status === "ok", serviceUrl, modelReady: health.model_ready, profiles: health.profiles ?? [], jobs };
    lastSnapshot = snapshot;
    return snapshot;
  } catch (error) {
    if (lastSnapshot) return { ...lastSnapshot, sleeping: true };
    try {
      const health = await fetchJson<{ status: string; model_ready: boolean; profiles?: VideoProfile[] }>("/health", undefined, true);
      const jobs = await fetchJson<VideoJob[]>("/jobs", undefined, false);
      const snapshot = { healthy: health.status === "ok", sleeping: false, serviceUrl, modelReady: health.model_ready, profiles: health.profiles ?? [], jobs };
      lastSnapshot = snapshot;
      return snapshot;
    } catch {
      // Return the original connection failure below.
    }
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

export async function startVideoModelDownload(profile = "ltx23-q4"): Promise<Record<string, unknown>> {
  return await fetchJson<Record<string, unknown>>(`/model/download?profile=${encodeURIComponent(profile)}`, { method: "POST" });
}

export async function cancelVideoJob(id: string): Promise<Record<string, unknown>> {
  return await fetchJson<Record<string, unknown>>(`/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

export async function deleteVideoJob(id: string): Promise<Record<string, unknown>> {
  return await fetchJson<Record<string, unknown>>(`/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function fetchVideoOutput(id: string): Promise<Response> {
  const response = await managedServiceFetch("video", videoUrl(`/jobs/${encodeURIComponent(id)}/video`), undefined, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
  return response;
}

export function videoOutputUrl(id: string): string {
  return `/api/video/output?id=${encodeURIComponent(id)}`;
}
