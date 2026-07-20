import { getConfig } from "./config";

export type MusicMode = "create" | "reference" | "edit" | "stems";
export type MusicTaskType = "text2music" | "cover" | "repaint" | "complete" | "lego" | "extract" | "reference" | "separate";
export type MusicJobStatus = "preparing" | "queued" | "waiting" | "running" | "restoring" | "completed" | "failed" | "cancelled";

export type MusicProfile = {
  id: string;
  name: string;
  backend: "ace" | "levo";
  model: string;
  lmModel?: string | null;
  description: string;
  recommended: boolean;
  experimental: boolean;
  noncommercial: boolean;
  modes: MusicMode[];
  taskTypes: MusicTaskType[];
  duration: { min: number; max: number; default: number };
  stepOptions: number[];
  defaultSteps?: number | null;
  outputFormats: string[];
  expectedVramGb: number;
  ready: boolean;
  availabilityReason?: string | null;
  licenseHash?: string;
  licenseAccepted: boolean;
};

export type MusicJob = {
  id: string;
  profile_id: string;
  profile_name?: string;
  mode: MusicMode;
  task_type: MusicTaskType;
  status: MusicJobStatus;
  stage: string;
  progress: number;
  eta_seconds?: number | null;
  payload: Record<string, unknown>;
  assets: Record<string, string>;
  metrics: Record<string, number | string | null>;
  error?: string | null;
  recovery_state?: string | null;
  cancel_requested?: boolean;
  noncommercial?: boolean;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
};

export type MusicSnapshot = {
  healthy: boolean;
  profiles: MusicProfile[];
  jobs: MusicJob[];
  license: { levo2: { hash: string; text: string; accepted: boolean } };
  error?: string;
};

function musicUrl(path: string): string {
  return `${getConfig().musicUrl.replace(/\/$/, "")}${path}`;
}

async function fetchMusicJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(musicUrl(path), { ...init, cache: "no-store" });
  if (!response.ok) {
    const text = await response.text();
    try {
      const parsed = JSON.parse(text) as { detail?: string; error?: string };
      throw new Error(parsed.detail ?? parsed.error ?? `Music request failed (${response.status}).`);
    } catch (error) {
      if (error instanceof Error && !error.message.startsWith("Unexpected token")) throw error;
      throw new Error(text || `Music request failed (${response.status}).`);
    }
  }
  return await response.json() as T;
}

export async function getMusicSnapshot(): Promise<MusicSnapshot> {
  try {
    return await fetchMusicJson<MusicSnapshot>("/?limit=150");
  } catch (error) {
    return {
      healthy: false,
      profiles: [],
      jobs: [],
      license: { levo2: { hash: "", text: "", accepted: false } },
      error: error instanceof Error ? error.message : "Music service unavailable",
    };
  }
}

export async function createMusicJob(payload: FormData | Record<string, unknown>): Promise<MusicJob> {
  return await fetchMusicJson<MusicJob>("/jobs", {
    method: "POST",
    headers: payload instanceof FormData ? undefined : { "Content-Type": "application/json" },
    body: payload instanceof FormData ? payload : JSON.stringify(payload),
  });
}

export async function getMusicJob(id: string): Promise<MusicJob> {
  return await fetchMusicJson<MusicJob>(`/jobs/${encodeURIComponent(id)}`);
}

export async function musicJobAction(id: string, action: "cancel" | "retry"): Promise<{ ok: boolean; job: MusicJob }> {
  return await fetchMusicJson(`/jobs/${encodeURIComponent(id)}/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}

export async function deleteMusicJob(id: string): Promise<{ ok: boolean }> {
  return await fetchMusicJson(`/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function acceptLevoLicense(licenseHash: string): Promise<{ ok: boolean; licenseHash: string }> {
  return await fetchMusicJson("/licenses/levo2/accept", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accepted: true, licenseHash, acceptedBy: "hendo420" }),
  });
}

export async function fetchMusicOutput(id: string, asset = "master"): Promise<Response> {
  const response = await fetch(musicUrl(`/jobs/${encodeURIComponent(id)}/output?asset=${encodeURIComponent(asset)}`), { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return response;
}

export function musicOutputUrl(id: string, asset = "master"): string {
  return `/api/music/jobs/${encodeURIComponent(id)}/output?asset=${encodeURIComponent(asset)}`;
}
