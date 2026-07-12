import { getConfig } from "./config";
import { managedServiceFetch } from "./managed-service";

export const WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3", "turbo"] as const;

export type WhisperModel = (typeof WHISPER_MODELS)[number];
export type WhisperTask = "transcribe" | "translate";
export type WhisperJobStatus = "queued" | "running" | "completed" | "failed";

export type WhisperJob = {
  id: string;
  filename: string;
  model: WhisperModel;
  task: WhisperTask;
  language?: string | null;
  status: WhisperJobStatus;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  transcript_path?: string | null;
  transcript_name?: string | null;
  duration_seconds?: number | null;
  media_duration_seconds?: number | null;
  processed_seconds?: number | null;
  progress_percent?: number | null;
  progress_label?: string | null;
  eta_seconds?: number | null;
  error?: string | null;
};

export type WhisperSnapshot = {
  healthy: boolean;
  serviceUrl: string;
  models: readonly WhisperModel[];
  jobs: WhisperJob[];
  sleeping?: boolean;
  error?: string;
};

let lastSnapshot: WhisperSnapshot | null = null;

function whisperUrl(path: string): string {
  return `${getConfig().whisperUrl.replace(/\/$/, "")}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit, wake = true): Promise<T> {
  const response = await managedServiceFetch("whisper", whisperUrl(path), {
    ...init,
  }, { wake });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export async function getWhisperSnapshot(): Promise<WhisperSnapshot> {
  const serviceUrl = getConfig().whisperUrl;
  try {
    const [health, jobs] = await Promise.all([
      fetchJson<{ status: string; models?: WhisperModel[] }>("/health", undefined, false),
      fetchJson<WhisperJob[]>("/jobs", undefined, false),
    ]);
    const snapshot = {
      healthy: health.status === "ok",
      serviceUrl,
      models: health.models ?? WHISPER_MODELS,
      jobs,
    };
    lastSnapshot = snapshot;
    return snapshot;
  } catch (error) {
    if (lastSnapshot) return { ...lastSnapshot, sleeping: true };
    try {
      const health = await fetchJson<{ status: string; models?: WhisperModel[] }>("/health", undefined, true);
      const jobs = await fetchJson<WhisperJob[]>("/jobs", undefined, false);
      const snapshot = { healthy: health.status === "ok", sleeping: false, serviceUrl, models: health.models ?? WHISPER_MODELS, jobs };
      lastSnapshot = snapshot;
      return snapshot;
    } catch {
      // Return the original connection failure below.
    }
    return {
      healthy: false,
      serviceUrl,
      models: WHISPER_MODELS,
      jobs: [],
      error: error instanceof Error ? error.message : "Whisper service unavailable",
    };
  }
}

export async function createWhisperJob(formData: FormData): Promise<WhisperJob> {
  return await fetchJson<WhisperJob>("/jobs", {
    method: "POST",
    body: formData,
  });
}

export async function deleteWhisperJob(id: string): Promise<Record<string, unknown>> {
  return await fetchJson<Record<string, unknown>>(`/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function fetchWhisperTranscript(id: string): Promise<Response> {
  const response = await managedServiceFetch("whisper", whisperUrl(`/jobs/${encodeURIComponent(id)}/transcript`), undefined, { wake: true });
  if (!response.ok) throw new Error(await response.text());
  return response;
}

export function whisperTranscriptUrl(id: string): string {
  return `/api/whisper/output?id=${encodeURIComponent(id)}`;
}
