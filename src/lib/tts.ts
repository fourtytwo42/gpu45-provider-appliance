import { getConfig } from "./config";
import { managedServiceFetch } from "./managed-service";

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

export type TtsAudiobookChunk = {
  index: number;
  status: "pending" | "running" | "completed" | "failed" | "flagged" | "skipped";
  role?: "intro" | "content" | "skipped_front_matter" | string;
  pause_after_ms?: number;
  regenerate_requested?: boolean;
  regenerate_requested_at?: string;
  regenerate_count?: number;
  skipped_reason?: string;
  text: string;
  text_chars: number;
  output_path?: string;
  output_bytes?: number;
  audio_url?: string;
  quality?: { ok?: boolean; reasons?: string[]; duration_seconds?: number; rms?: number; peak?: number; zero_crossing_rate?: number } | null;
  error?: string;
  started_at?: string;
  finished_at?: string;
  updated_at?: string;
};

export type TtsAudiobookJob = {
  id: string;
  kind: "audiobook";
  status: "queued" | "running" | "stopped" | "completed" | "failed" | "needs_review";
  title: string;
  source_filename: string;
  model_id: string;
  model_name?: string;
  speech_engine?: "qwen" | "pocket";
  chunk_chars?: number;
  split_strategy?: "sentence" | string;
  target_chunk_chars?: number;
  total_chunks: number;
  completed_chunks: number;
  failed_chunks: number;
  current_chunk?: number | null;
  progress_label: string;
  progress_percent: number;
  eta_seconds?: number | null;
  stop_requested?: boolean;
  stitched_audio_url?: string;
  text_chars: number;
  chunks: TtsAudiobookChunk[];
  error?: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  updated_at: string;
};


export type TtsPresentationSlide = {
  index: number;
  slide_number: number;
  status: "pending" | "running" | "completed" | "failed" | "flagged" | "empty";
  text?: string;
  text_chars: number;
  output_path?: string;
  output_bytes?: number;
  audio_url?: string;
  audio_duration_seconds?: number;
  quality?: { ok?: boolean; reasons?: string[]; duration_seconds?: number; chunks?: number } | null;
  error?: string;
  started_at?: string;
  finished_at?: string;
  updated_at?: string;
};

export type TtsPresentationJob = {
  id: string;
  kind: "presentation";
  status: "queued" | "running" | "stopped" | "completed" | "failed" | "needs_review" | "paused";
  title: string;
  source_filename: string;
  model_id: string;
  model_name?: string;
  speech_engine?: "qwen" | "pocket";
  total_slides: number;
  narration_slides: number;
  completed_slides: number;
  failed_slides: number;
  current_slide?: number | null;
  progress_label: string;
  progress_percent: number;
  eta_seconds?: number | null;
  stop_requested?: boolean;
  output_url?: string;
  output_path?: string;
  output_bytes?: number;
  slides: TtsPresentationSlide[];
  error?: string;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  updated_at: string;
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
  audiobookJobs: TtsAudiobookJob[];
  presentationJobs: TtsPresentationJob[];
  sleeping?: boolean;
  error?: string;
};

type JsonValue = Record<string, unknown>;

let snapshotCache: { value: TtsSnapshot; expiresAt: number } | null = null;
let snapshotRequest: Promise<TtsSnapshot> | null = null;

function ttsUrl(path: string): string {
  return `${getConfig().ttsUrl.replace(/\/$/, "")}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit, wake = true): Promise<T> {
  const response = await managedServiceFetch("tts", ttsUrl(path), {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  }, { wake, startupTimeoutMs: 120_000 });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `TTS request failed with HTTP ${response.status}`);
  }
  return await response.json() as T;
}

export async function getTtsSnapshot(): Promise<TtsSnapshot> {
  const serviceUrl = getConfig().ttsUrl;
  if (snapshotCache && snapshotCache.expiresAt > Date.now()) return snapshotCache.value;
  if (snapshotRequest) return snapshotRequest;
  snapshotRequest = (async () => {
    try {
      const payload = await fetchJson<Omit<TtsSnapshot, "healthy" | "serviceUrl">>("/snapshot", undefined, false);
      const value: TtsSnapshot = { healthy: true, serviceUrl, ...payload };
      snapshotCache = { value, expiresAt: Date.now() + 2000 };
      return value;
    } catch (error) {
      if (snapshotCache) return { ...snapshotCache.value, sleeping: true };
      try {
        const payload = await fetchJson<Omit<TtsSnapshot, "healthy" | "serviceUrl">>("/snapshot", undefined, true);
        const value: TtsSnapshot = { healthy: true, sleeping: false, serviceUrl, ...payload };
        snapshotCache = { value, expiresAt: Date.now() + 2000 };
        return value;
      } catch {
        // Return the original connection failure below.
      }
      return { healthy: false, serviceUrl, voices: [], voiceJobs: [], models: [], synthesisJobs: [], audiobookJobs: [], presentationJobs: [], error: error instanceof Error ? error.message : "TTS service unavailable" };
    } finally {
      snapshotRequest = null;
    }
  })();
  return snapshotRequest;
}

export async function createTtsVoice(payload: JsonValue): Promise<JsonValue> {
  return await fetchJson<JsonValue>("/voices", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function importTtsVoice(formData: FormData): Promise<JsonValue> {
  const response = await managedServiceFetch("tts", ttsUrl("/voices/import"), {
    method: "POST",
    body: formData,
  }, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as JsonValue;
}

export async function createTtsAudiobook(formData: FormData): Promise<TtsAudiobookJob> {
  const response = await managedServiceFetch("tts", ttsUrl("/audiobooks"), {
    method: "POST",
    body: formData,
  }, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as TtsAudiobookJob;
}

export async function stopTtsAudiobook(id: string): Promise<TtsAudiobookJob> {
  return await fetchJson<TtsAudiobookJob>(`/audiobooks/${encodeURIComponent(id)}/stop`, { method: "POST" });
}

export async function resumeTtsAudiobook(id: string): Promise<TtsAudiobookJob> {
  return await fetchJson<TtsAudiobookJob>(`/audiobooks/${encodeURIComponent(id)}/resume`, { method: "POST" });
}

export async function regenerateTtsAudiobookChunk(id: string, chunk: number): Promise<TtsAudiobookJob> {
  return await fetchJson<TtsAudiobookJob>(`/audiobooks/${encodeURIComponent(id)}/chunks/${chunk}/regenerate`, { method: "POST" });
}

export async function deleteTtsAudiobook(id: string): Promise<void> {
  const response = await managedServiceFetch("tts", ttsUrl(`/audiobooks/${encodeURIComponent(id)}`), { method: "DELETE" }, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
}

export async function fetchTtsAudiobookAudio(id: string, chunk?: number): Promise<Response> {
  const path = typeof chunk === "number" ? `/audiobooks/${encodeURIComponent(id)}/chunks/${chunk}/audio` : `/audiobooks/${encodeURIComponent(id)}/audio`;
  const response = await managedServiceFetch("tts", ttsUrl(path), undefined, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
  return response;
}


export async function createTtsPresentation(formData: FormData): Promise<TtsPresentationJob> {
  const response = await managedServiceFetch("tts", ttsUrl("/presentations"), {
    method: "POST",
    body: formData,
  }, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
  return await response.json() as TtsPresentationJob;
}

export async function stopTtsPresentation(id: string): Promise<TtsPresentationJob> {
  return await fetchJson<TtsPresentationJob>(`/presentations/${encodeURIComponent(id)}/stop`, { method: "POST" });
}

export async function resumeTtsPresentation(id: string): Promise<TtsPresentationJob> {
  return await fetchJson<TtsPresentationJob>(`/presentations/${encodeURIComponent(id)}/resume`, { method: "POST" });
}

export async function deleteTtsPresentation(id: string): Promise<void> {
  const response = await managedServiceFetch("tts", ttsUrl(`/presentations/${encodeURIComponent(id)}`), { method: "DELETE" }, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
}

export async function fetchTtsPresentationOutput(id: string): Promise<Response> {
  const response = await managedServiceFetch("tts", ttsUrl(`/presentations/${encodeURIComponent(id)}/output`), undefined, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
  return response;
}

export async function fetchTtsPresentationSlideAudio(id: string, slide: number): Promise<Response> {
  const response = await managedServiceFetch("tts", ttsUrl(`/presentations/${encodeURIComponent(id)}/slides/${slide}/audio`), undefined, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
  return response;
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
  const response = await managedServiceFetch("tts", ttsUrl(`/voices/${encodeURIComponent(id)}`), { method: "DELETE" }, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
}

export async function deleteTtsModel(id: string): Promise<void> {
  const response = await managedServiceFetch("tts", ttsUrl(`/models/${encodeURIComponent(id)}`), { method: "DELETE" }, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
}

export async function deleteTtsVoiceJob(id: string): Promise<void> {
  const response = await managedServiceFetch("tts", ttsUrl(`/voice-jobs/${encodeURIComponent(id)}`), { method: "DELETE" }, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
}

export async function synthesizeTts(payload: JsonValue): Promise<Response> {
  const response = await managedServiceFetch("tts", ttsUrl("/synthesize"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }, { wake: true, startupTimeoutMs: 120_000 });
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
  const response = await managedServiceFetch("tts", ttsUrl(`/synthesis-jobs/${encodeURIComponent(id)}`), { method: "DELETE" }, { wake: true, startupTimeoutMs: 120_000 });
  if (!response.ok) throw new Error(await response.text());
}

export async function fetchTtsSynthesisAudio(id: string): Promise<Response> {
  const response = await managedServiceFetch("tts", ttsUrl(`/synthesis-jobs/${encodeURIComponent(id)}/audio`), undefined, { wake: true, startupTimeoutMs: 120_000 });
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

export function ttsAudiobookAudioUrl(id: string, options: { chunk?: number; download?: boolean; version?: number | string } = {}): string {
  const params = new URLSearchParams({ id });
  if (typeof options.chunk === "number") params.set("chunk", String(options.chunk));
  if (options.download) params.set("download", "1");
  if (options.version !== undefined) params.set("v", String(options.version));
  return `/api/tts/audiobook/audio?${params.toString()}`;
}


export function ttsPresentationOutputUrl(id: string, options: { download?: boolean; version?: number | string } = {}): string {
  const params = new URLSearchParams({ id });
  if (options.download) params.set("download", "1");
  if (options.version !== undefined) params.set("v", String(options.version));
  return `/api/tts/presentation/output?${params.toString()}`;
}

export function ttsPresentationSlideAudioUrl(id: string, slide: number, options: { download?: boolean; version?: number | string } = {}): string {
  const params = new URLSearchParams({ id, slide: String(slide) });
  if (options.download) params.set("download", "1");
  if (options.version !== undefined) params.set("v", String(options.version));
  return `/api/tts/presentation/output?${params.toString()}`;
}
