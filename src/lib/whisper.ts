import { getConfig } from "./config";

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
  error?: string;
};

function whisperUrl(path: string): string {
  return `${getConfig().whisperUrl.replace(/\/$/, "")}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(whisperUrl(path), {
    ...init,
    cache: "no-store",
  });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as T;
}

export async function getWhisperSnapshot(): Promise<WhisperSnapshot> {
  const serviceUrl = getConfig().whisperUrl;
  try {
    const [health, jobs] = await Promise.all([
      fetchJson<{ status: string; models?: WhisperModel[] }>("/health"),
      fetchJson<WhisperJob[]>("/jobs"),
    ]);
    return {
      healthy: health.status === "ok",
      serviceUrl,
      models: health.models ?? WHISPER_MODELS,
      jobs,
    };
  } catch (error) {
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
  const response = await fetch(whisperUrl(`/jobs/${encodeURIComponent(id)}/transcript`), { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return response;
}

export function whisperTranscriptUrl(id: string): string {
  return `/api/whisper/output?id=${encodeURIComponent(id)}`;
}
