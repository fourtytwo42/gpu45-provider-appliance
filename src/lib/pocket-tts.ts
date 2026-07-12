import { getConfig } from "./config";

export type PocketTtsVoice = {
  id: string;
  name: string;
  language: string;
  kind: "builtin" | "clone";
  created_at?: string;
};

export type PocketTtsJob = {
  id: string;
  kind: "pocket_synthesis";
  engine: "pocket-tts";
  status: "queued" | "running" | "completed" | "failed";
  voice_id: string;
  voice_name: string;
  language: string;
  text: string;
  text_chars: number;
  progress_percent: number;
  progress_label: string;
  elapsed_seconds?: number;
  duration_seconds?: number;
  output_bytes?: number;
  error?: string;
  created_at: string;
  updated_at: string;
  finished_at?: string;
};

export type PocketTtsSnapshot = {
  healthy: boolean;
  serviceUrl: string;
  device: "cpu";
  modelLoaded: boolean;
  voices: PocketTtsVoice[];
  jobs: PocketTtsJob[];
  error?: string;
};

function serviceUrl(path: string): string {
  return `${getConfig().pocketTtsUrl.replace(/\/$/, "")}${path}`;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(serviceUrl(path), { ...init, cache: "no-store" });
  if (!response.ok) throw new Error(await response.text() || `Pocket TTS returned HTTP ${response.status}`);
  return await response.json() as T;
}

export async function getPocketTtsSnapshot(): Promise<PocketTtsSnapshot> {
  const url = getConfig().pocketTtsUrl;
  try {
    const [health, voices, jobs] = await Promise.all([
      json<{ device: "cpu"; model_loaded: boolean }>("/health"),
      json<PocketTtsVoice[]>("/voices"),
      json<PocketTtsJob[]>("/jobs"),
    ]);
    return { healthy: true, serviceUrl: url, device: health.device, modelLoaded: health.model_loaded, voices, jobs };
  } catch (error) {
    return { healthy: false, serviceUrl: url, device: "cpu", modelLoaded: false, voices: [], jobs: [], error: error instanceof Error ? error.message : "Pocket TTS unavailable" };
  }
}

export async function createPocketTtsJob(text: string, voiceId: string): Promise<PocketTtsJob> {
  return await json<PocketTtsJob>("/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice_id: voiceId }),
  });
}

export async function importPocketTtsVoice(formData: FormData): Promise<PocketTtsVoice> {
  const response = await fetch(serviceUrl("/voices"), { method: "POST", body: formData, cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as PocketTtsVoice;
}

export async function deletePocketTtsJob(id: string): Promise<void> {
  await json(`/jobs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function deletePocketTtsVoice(id: string): Promise<void> {
  await json(`/voices/${encodeURIComponent(id.replace(/^clone:/, ""))}`, { method: "DELETE" });
}

export async function fetchPocketTtsAudio(id: string, download = false): Promise<Response> {
  const response = await fetch(serviceUrl(`/jobs/${encodeURIComponent(id)}/audio?download=${download ? "true" : "false"}`), { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return response;
}
