import { getConfig } from "./config";

export type TtsVoice = {
  id: string;
  name: string;
  instruct: string;
  language: string;
  device?: string;
  source?: "upload" | string;
  source_filename?: string;
  paragraph_text?: string;
  paragraph_path?: string;
  transcript_source?: "submitted" | "whisper" | string;
  created_at: string;
};

export type TtsVoiceJob = {
  id: string;
  kind: "voice" | "voice_import";
  status: "queued" | "running" | "complete" | "failed";
  name?: string;
  language: string;
  device: string;
  voice_id?: string;
  voice?: TtsVoice;
  source_filename?: string;
  transcript_source?: string;
  error?: string;
  progress_label: string;
  progress_percent: number;
  eta_seconds?: number | null;
  elapsed_seconds?: number;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  updated_at: string;
};

export type TtsModel = {
  id: string;
  name: string;
  voice_id: string;
  status: "training" | "ready" | "failed";
  progress_label?: string;
  progress_percent?: number;
  eta_seconds?: number | null;
  elapsed_seconds?: number;
  model_path?: string;
  speaker_name?: string;
  sample_path?: string;
  error?: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  updated_at?: string;
};

export type TtsSynthesisJob = {
  id: string;
  kind: "synthesis";
  status: "queued" | "running" | "completed" | "failed";
  model_id: string;
  model_name?: string;
  text?: string;
  text_source?: "submitted" | "recovered_transcript" | string;
  text_chars: number;
  progress_label: string;
  progress_percent: number;
  eta_seconds?: number | null;
  elapsed_seconds?: number;
  duration_seconds?: number;
  output_path?: string;
  output_bytes?: number;
  error?: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  updated_at: string;
};

export type TtsSnapshot = {
  healthy: boolean;
  serviceUrl: string;
  voices: TtsVoice[];
  voiceJobs: TtsVoiceJob[];
  models: TtsModel[];
  synthesisJobs: TtsSynthesisJob[];
  error?: string;
};

type JsonValue = Record<string, unknown>;

function ttsUrl(path: string): string {
  return `${getConfig().ttsUrl.replace(/\/$/, "")}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(ttsUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `TTS request failed with HTTP ${response.status}`);
  }
  return await response.json() as T;
}

export async function getTtsSnapshot(): Promise<TtsSnapshot> {
  const serviceUrl = getConfig().ttsUrl;
  try {
    await fetchJson<{ status: string }>("/health");
    const [voices, models] = await Promise.all([
      fetchJson<TtsVoice[]>("/voices"),
      fetchJson<TtsModel[]>("/models"),
    ]);
    const voiceJobs = await fetchJson<TtsVoiceJob[]>("/voice-jobs").catch(() => []);
    const synthesisJobs = await fetchJson<TtsSynthesisJob[]>("/synthesis-jobs").catch(() => []);
    return { healthy: true, serviceUrl, voices, voiceJobs, models, synthesisJobs };
  } catch (error) {
    return {
      healthy: false,
      serviceUrl,
      voices: [],
      voiceJobs: [],
      models: [],
      synthesisJobs: [],
      error: error instanceof Error ? error.message : "TTS service unavailable",
    };
  }
}

export async function createTtsVoice(payload: JsonValue): Promise<JsonValue> {
  return await fetchJson<JsonValue>("/voices", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function importTtsVoice(formData: FormData): Promise<JsonValue> {
  const response = await fetch(ttsUrl("/voices/import"), {
    method: "POST",
    body: formData,
    cache: "no-store",
  });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as JsonValue;
}

export async function trainTtsModel(payload: JsonValue): Promise<JsonValue> {
  return await fetchJson<JsonValue>("/models", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function renameTtsVoice(id: string, name: string): Promise<TtsVoice> {
  return await fetchJson<TtsVoice>(`/voices/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export async function renameTtsModel(id: string, name: string): Promise<TtsModel> {
  return await fetchJson<TtsModel>(`/models/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export async function deleteTtsVoice(id: string): Promise<void> {
  const response = await fetch(ttsUrl(`/voices/${encodeURIComponent(id)}`), { method: "DELETE", cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
}

export async function deleteTtsModel(id: string): Promise<void> {
  const response = await fetch(ttsUrl(`/models/${encodeURIComponent(id)}`), { method: "DELETE", cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
}

export async function deleteTtsVoiceJob(id: string): Promise<void> {
  const response = await fetch(ttsUrl(`/voice-jobs/${encodeURIComponent(id)}`), { method: "DELETE", cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
}

export async function synthesizeTts(payload: JsonValue): Promise<Response> {
  const response = await fetch(ttsUrl("/synthesize"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  if (!response.ok) throw new Error(await response.text());
  return response;
}

export async function createTtsSynthesisJob(payload: JsonValue): Promise<TtsSynthesisJob> {
  return await fetchJson<TtsSynthesisJob>("/synthesis-jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteTtsSynthesisJob(id: string): Promise<void> {
  const response = await fetch(ttsUrl(`/synthesis-jobs/${encodeURIComponent(id)}`), { method: "DELETE", cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
}

export async function fetchTtsSynthesisAudio(id: string): Promise<Response> {
  const response = await fetch(ttsUrl(`/synthesis-jobs/${encodeURIComponent(id)}/audio`), { cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return response;
}

export function ttsSampleUrl(kind: "voices" | "models", id: string): string {
  return `/api/tts/sample?kind=${kind}&id=${encodeURIComponent(id)}`;
}

export function ttsSynthesisAudioUrl(id: string, download = false): string {
  const params = new URLSearchParams({ id });
  if (download) params.set("download", "1");
  return `/api/tts/audio?${params.toString()}`;
}
