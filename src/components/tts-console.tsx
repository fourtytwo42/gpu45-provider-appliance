"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, Clock, Download, Mic2, PauseCircle, Play, RefreshCw, RotateCcw, Sparkles, Trash2, Upload, Wand2 } from "lucide-react";
import { SectionCard } from "./section-card";
import type { TtsAudiobookJob, TtsModel, TtsPresentationJob, TtsSnapshot, TtsSynthesisJob, TtsVoice, TtsVoiceJob } from "@/lib/tts";
import { ttsAudiobookAudioUrl, ttsPresentationOutputUrl, ttsPresentationSlideAudioUrl, ttsSampleUrl, ttsSynthesisAudioUrl } from "@/lib/tts";
import { cn } from "@/lib/cn";
import type { PocketTtsSnapshot } from "@/lib/pocket-tts";

type Status = "idle" | "working" | "error";
const AUDIOBOOK_CHUNKS_PER_PAGE = 8;
const MAX_PRESENTATION_BYTES = 120 * 1024 * 1024;

async function parseJson(response: Response): Promise<Record<string, unknown>> {
  const text = await response.text();
  let json: Record<string, unknown>;
  try {
    json = JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new Error(`TTS request returned ${response.status} ${response.statusText || "without JSON"}.`);
  }
  if (!response.ok) throw new Error(String(json.error ?? json.detail ?? "TTS request failed"));
  return json;
}

function formatDuration(seconds?: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "unknown";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (hours > 0) return `${hours}h ${Math.floor((total % 3600) / 60)}m`;
  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`;
}

function formatEta(seconds: number | null | undefined, isRunning: boolean): string {
  if (isRunning && seconds != null && Number.isFinite(seconds) && seconds <= 0) return "over estimate";
  return formatDuration(seconds);
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function progressValue(job: TtsVoiceJob): number {
  return Math.max(0, Math.min(100, Number(job.progress_percent ?? 0)));
}

function modelProgressValue(model: TtsModel): number {
  if (model.status === "ready") return 100;
  if (model.status === "failed") return Number(model.progress_percent ?? 100);
  return Math.max(0, Math.min(100, Number(model.progress_percent ?? 1)));
}

function synthesisProgressValue(job: TtsSynthesisJob): number {
  return Math.max(0, Math.min(100, Number(job.progress_percent ?? 0)));
}

function audiobookProgressValue(job: TtsAudiobookJob): number {
  return Math.max(0, Math.min(100, Number(job.progress_percent ?? 0)));
}

function presentationProgressValue(job: TtsPresentationJob): number {
  return Math.max(0, Math.min(100, Number(job.progress_percent ?? 0)));
}

export function TtsConsole({ initialSnapshot }: { initialSnapshot: TtsSnapshot }) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState("");
  const [activeSynthesisId, setActiveSynthesisId] = useState<string | null>(null);
  const [audiobookChunkPages, setAudiobookChunkPages] = useState<Record<string, number>>({});
  const [audiobookEngine, setAudiobookEngine] = useState<"qwen" | "pocket">("qwen");
  const [presentationEngine, setPresentationEngine] = useState<"qwen" | "pocket">("qwen");
  const [pocket, setPocket] = useState<PocketTtsSnapshot>({ healthy: false, serviceUrl: "", device: "cpu", modelLoaded: false, voices: [], jobs: [] });
  const readyModels = useMemo(() => snapshot.models.filter((model) => model.status === "ready"), [snapshot.models]);
  const activeSynthesisJobs = useMemo(() => (
    snapshot.synthesisJobs
      .filter((job) => job.status === "queued" || job.status === "running")
      .slice()
      .sort((a, b) => String(b.updated_at ?? b.created_at).localeCompare(String(a.updated_at ?? a.created_at)))
  ), [snapshot.synthesisJobs]);
  const synthesisHistory = useMemo(() => (
    snapshot.synthesisJobs
      .filter((job) => job.status === "completed" || job.status === "failed")
      .slice()
      .sort((a, b) => String(b.finished_at ?? b.updated_at).localeCompare(String(a.finished_at ?? a.updated_at)))
  ), [snapshot.synthesisJobs]);
  const audiobookJobs = useMemo(() => (
    snapshot.audiobookJobs
      .slice()
      .sort((a, b) => String(b.updated_at ?? b.created_at).localeCompare(String(a.updated_at ?? a.created_at)))
  ), [snapshot.audiobookJobs]);
  const activeAudiobookJobs = useMemo(() => audiobookJobs.filter((job) => job.status === "queued" || job.status === "running"), [audiobookJobs]);
  const presentationJobs = useMemo(() => (
    snapshot.presentationJobs
      .slice()
      .sort((a, b) => String(b.updated_at ?? b.created_at).localeCompare(String(a.updated_at ?? a.created_at)))
  ), [snapshot.presentationJobs]);
  const activePresentationJobs = useMemo(() => presentationJobs.filter((job) => job.status === "queued" || job.status === "running"), [presentationJobs]);
  const activePocketJobs = useMemo(() => pocket.jobs.filter((job) => job.status === "queued" || job.status === "running"), [pocket.jobs]);

  const reconcileSynthesisStatus = useCallback((next: TtsSnapshot, id = activeSynthesisId): void => {
    if (!id) return;
    const job = next.synthesisJobs.find((item) => item.id === id);
    if (!job) return;
    if (job.status === "completed") {
      setStatus("idle");
      setMessage("Audio generated.");
    }
    if (job.status === "failed") {
      setStatus("error");
      setMessage(job.error ?? "TTS synthesis failed.");
    }
  }, [activeSynthesisId]);

  const refresh = useCallback(async (activeId = activeSynthesisId): Promise<void> => {
    const response = await fetch("/api/tts", { cache: "no-store" });
    const next = await response.json() as TtsSnapshot;
    setSnapshot(next);
    reconcileSynthesisStatus(next, activeId);
  }, [activeSynthesisId, reconcileSynthesisStatus]);

  const refreshPocket = useCallback(async (): Promise<void> => {
    const response = await fetch("/api/tts/pocket", { cache: "no-store" });
    setPocket(await response.json() as PocketTtsSnapshot);
  }, []);

  async function run(action: () => Promise<void>, workingMessage: string): Promise<void> {
    setStatus("working");
    setMessage(workingMessage);
    try {
      await action();
      await refresh();
      setStatus("idle");
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "TTS action failed");
    }
  }

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (activeSynthesisJobs.length === 0 && activeAudiobookJobs.length === 0 && activePresentationJobs.length === 0) return undefined;
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [activeSynthesisJobs.length, activeAudiobookJobs.length, activePresentationJobs.length, refresh]);

  useEffect(() => {
    const initial = window.setTimeout(() => void refreshPocket().catch(() => undefined), 0);
    const timer = window.setInterval(() => void refreshPocket().catch(() => undefined), activePocketJobs.length > 0 ? 1000 : 5000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [activePocketJobs.length, refreshPocket]);

  async function createVoice(formData: FormData): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "createVoice",
          name: formData.get("name"),
          language: formData.get("language") || "English",
          instruct: formData.get("instruct"),
          device: formData.get("device") || undefined,
        }),
      });
      await parseJson(response);
      setMessage("Voice generation queued. Progress refreshes automatically.");
    }, "Queueing prompt-designed reference voice.");
  }

  async function importVoice(formData: FormData): Promise<void> {
    setStatus("working");
    setMessage("Uploading reference media.");
    try {
      const response = await fetch("/api/tts", {
        method: "POST",
        body: formData,
      });
      await parseJson(response);
      setMessage("Voice import queued. Progress refreshes automatically.");
      await refresh();
      setStatus("idle");
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "Voice import failed");
    }
  }

  async function trainModel(voice: TtsVoice): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "trainModel",
          voiceId: voice.id,
          name: `${voice.name}_clone`,
        }),
      });
      await parseJson(response);
      setMessage("Training queued. Status refreshes automatically.");
    }, "Starting voice-clone training from the selected reference voice.");
  }

  async function deleteItem(action: "deleteVoice" | "deleteModel" | "deleteVoiceJob" | "deleteSynthesisJob", id: string): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, id }),
      });
      await parseJson(response);
      setMessage("Deleted.");
    }, "Deleting TTS asset.");
  }

  async function synthesize(formData: FormData): Promise<void> {
    setStatus("working");
    setMessage("Queueing synthesis job.");
    try {
      const modelId = String(formData.get("modelId") ?? "");
      if (!modelId) {
        throw new Error("Choose a trained voice model before generating audio.");
      }
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "createSynthesisJob",
          text: formData.get("text"),
          modelId,
        }),
      });
      const json = await parseJson(response);
      const job = json.job as TtsSynthesisJob | undefined;
      if (!job?.id) throw new Error("Synthesis job did not return an id.");
      setActiveSynthesisId(job.id);
      setMessage("Synthesis queued. Progress refreshes automatically.");
      await refresh(job.id);
    } catch (error) {
      const detail = error instanceof Error ? error.message : "TTS synthesis failed";
      setStatus("error");
      setMessage(detail);
    }
  }

  async function synthesizePocket(formData: FormData): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/tts/pocket", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "createJob", text: formData.get("text"), voiceId: formData.get("voiceId") }),
      });
      await parseJson(response);
      await refreshPocket();
      setMessage("Pocket TTS synthesis queued on CPU. The GPU and LLM remain available.");
    }, "Queueing Pocket TTS synthesis.");
  }

  async function importPocketVoice(formData: FormData): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/tts/pocket", { method: "POST", body: formData });
      await parseJson(response);
      await refreshPocket();
      setMessage("Pocket TTS voice clone imported and cached.");
    }, "Encoding Pocket TTS voice clone.");
  }

  async function deletePocket(action: "deleteJob" | "deleteVoice", id: string): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/tts/pocket", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, id }),
      });
      await parseJson(response);
      await refreshPocket();
      setMessage(action === "deleteJob" ? "Pocket TTS audio deleted." : "Pocket TTS voice deleted.");
    }, "Deleting Pocket TTS item.");
  }

  async function createAudiobook(formData: FormData): Promise<void> {
    setStatus("working");
    setMessage("Uploading document and queueing audiobook TTS.");
    try {
      const modelId = String(formData.get("model_id") ?? "");
      if (!modelId) throw new Error("Choose a trained voice model before creating an audiobook.");
      const response = await fetch("/api/tts", { method: "POST", body: formData });
      await parseJson(response);
      setMessage("Audiobook queued. Chunks appear as soon as they finish.");
      await refresh();
      setStatus("idle");
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "Audiobook upload failed");
    }
  }

  async function controlAudiobook(action: "stopAudiobook" | "resumeAudiobook" | "deleteAudiobook", id: string): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, id }),
      });
      await parseJson(response);
      setMessage(action === "stopAudiobook" ? "Stop requested. Current chunk may finish first." : action === "resumeAudiobook" ? "Audiobook resumed." : "Audiobook deleted.");
    }, action === "stopAudiobook" ? "Stopping audiobook." : action === "resumeAudiobook" ? "Resuming audiobook." : "Deleting audiobook.");
  }

  async function regenerateAudiobookChunk(id: string, chunk: number): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "regenerateAudiobookChunk", id, chunk }),
      });
      await parseJson(response);
      setMessage(`Chunk ${chunk + 1} queued for regeneration.`);
    }, `Regenerating chunk ${chunk + 1}.`);
  }


  async function createPresentation(formData: FormData): Promise<void> {
    setStatus("working");
    setMessage("Uploading PowerPoint and queueing slide narration.");
    try {
      const modelId = String(formData.get("model_id") ?? "");
      if (!modelId) throw new Error("Choose a trained voice model before narrating a PowerPoint.");
      const file = formData.get("file");
      if (!(file instanceof File) || file.size === 0) throw new Error("Choose a PPTX file before creating narration.");
      if (!file.name.toLowerCase().endsWith(".pptx")) throw new Error("PowerPoint narration accepts .pptx files only.");
      if (file.size > MAX_PRESENTATION_BYTES) throw new Error("PPTX files must be 120 MB or smaller.");
      const response = await fetch("/api/tts", { method: "POST", body: formData });
      await parseJson(response);
      setMessage("PowerPoint narration queued. Slide audio appears as each slide completes.");
      await refresh();
      setStatus("idle");
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "PowerPoint narration upload failed");
    }
  }

  async function controlPresentation(action: "stopPresentation" | "resumePresentation" | "deletePresentation", id: string): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, id }),
      });
      await parseJson(response);
      setMessage(action === "stopPresentation" ? "Stop requested. Current slide may finish first." : action === "resumePresentation" ? "Presentation narration resumed." : "Presentation job deleted.");
    }, action === "stopPresentation" ? "Stopping presentation narration." : action === "resumePresentation" ? "Resuming presentation narration." : "Deleting presentation job.");
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(380px,0.85fr)]">
      <section className="xl:col-span-2">
        <div className="flex flex-wrap items-center justify-between gap-3 border border-white/10 bg-[#07121a] px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center border border-cyan-400/40 bg-cyan-400/10 text-cyan-200">
              <Mic2 className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-white">Qwen3-TTS Voice Lab</h1>
              <p className="text-sm text-slate-400">{snapshot.serviceUrl}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={cn("border px-3 py-1 text-sm", snapshot.healthy ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-red-400/40 bg-red-400/10 text-red-200")}>
              {snapshot.healthy ? "online" : "offline"}
            </span>
            <button className="inline-flex items-center gap-2 border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 hover:bg-white/10" onClick={() => void refresh()}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </button>
          </div>
        </div>
        {message ? (
          <div className={cn("mt-3 border px-4 py-3 text-sm", status === "error" ? "border-red-400/30 bg-red-500/10 text-red-200" : "border-cyan-400/30 bg-cyan-500/10 text-cyan-100")}>
            {status === "working" ? "Working: " : null}{message}
          </div>
        ) : null}
        {!snapshot.healthy && snapshot.error ? <div className="mt-3 border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{snapshot.error}</div> : null}
      </section>

      <SectionCard title="Design Voice" description="Generate a reference voice from a prompt. Train it after you like the sample.">
        <form action={(formData) => void createVoice(formData)} className="grid gap-3">
          <input name="name" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60" placeholder="voice name" />
          <input name="language" defaultValue="English" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60" />
          <select name="device" defaultValue="cpu" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60">
            <option value="cpu">CPU, leaves GPU for LLM</option>
            <option value="cuda:0">GPU, faster test run</option>
          </select>
          <textarea
            name="instruct"
            required
            rows={5}
            className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60"
            placeholder="Warm adult narrator, clear consonants, natural pacing, quiet confidence."
          />
          <button disabled={status === "working"} className="inline-flex items-center justify-center gap-2 border border-cyan-400/40 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-400/20 disabled:opacity-50">
            <Wand2 className="h-4 w-4" />
            Generate Voice
          </button>
        </form>
      </SectionCard>

      <SectionCard title="Import Voice" description="Clone from uploaded audio or video.">
        <form action={(formData) => void importVoice(formData)} className="grid gap-3">
          <input type="hidden" name="action" value="importVoice" />
          <input name="name" required className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60" placeholder="voice name" />
          <input name="language" defaultValue="English" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60" />
          <input
            name="file"
            type="file"
            required
            accept="audio/*,video/*"
            className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-200 file:mr-3 file:border-0 file:bg-cyan-400/10 file:px-3 file:py-1 file:text-cyan-100"
          />
          <textarea
            name="transcript"
            rows={4}
            className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60"
            placeholder="Optional transcript for the uploaded voice sample."
          />
          <button disabled={status === "working"} className="inline-flex items-center justify-center gap-2 border border-cyan-400/40 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-400/20 disabled:opacity-50">
            <Upload className="h-4 w-4" />
            Import Voice
          </button>
        </form>
      </SectionCard>

      <SectionCard title="Synthesize" description="Generate audio with a trained voice model.">
        <form action={(formData) => void synthesize(formData)} className="grid gap-3">
          <select name="modelId" required className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60">
            <option value="">Choose trained voice model</option>
            {readyModels.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}
          </select>
          <textarea
            name="text"
            required
            rows={6}
            className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60"
            placeholder="Type the text to speak."
          />
          <button disabled={status === "working" || readyModels.length === 0} className="inline-flex items-center justify-center gap-2 border border-emerald-400/40 bg-emerald-400/10 px-4 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-400/20 disabled:opacity-50">
            <Play className="h-4 w-4" />
            Generate Audio
          </button>
          {readyModels.length === 0 ? <p className="text-sm text-slate-400">Train a voice model before synthesizing audio.</p> : null}
          {activeSynthesisJobs.length > 0 ? (
            <div className="grid gap-2">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-medium text-white">Active audio jobs</h3>
                <span className="text-xs text-slate-400">{activeSynthesisJobs.length} running</span>
              </div>
              {activeSynthesisJobs.map((job) => (
                <div key={job.id} className="border border-cyan-400/30 bg-cyan-500/10 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="font-medium text-white">{job.progress_label}</div>
                      <div className="text-xs text-slate-400">
                        {job.model_name ?? job.model_id} / {job.text_chars} chars
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
                      <Clock className="h-3.5 w-3.5" />
                      <span>elapsed {formatDuration(job.elapsed_seconds)}</span>
                      <span>ETA {formatEta(job.eta_seconds, job.status === "running" || job.status === "queued")}</span>
                    </div>
                  </div>
                  <div className="mt-3 h-2 overflow-hidden border border-white/10 bg-black/30">
                    <div className="h-full bg-cyan-300 transition-all" style={{ width: `${synthesisProgressValue(job)}%` }} />
                  </div>
                  <div className="mt-1 flex justify-between text-xs text-slate-400">
                    <span>{job.updated_at ? `Last update ${formatTimestamp(job.updated_at)}` : "Progress refreshes automatically."}</span>
                    <span>{synthesisProgressValue(job).toFixed(1)}%</span>
                  </div>
                </div>
              ))}
            </div>
          ) : null}
          <div className="grid gap-2">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-medium text-white">Generated audio history</h3>
              <span className="text-xs text-slate-400">{synthesisHistory.length} saved</span>
            </div>
            {synthesisHistory.length === 0 ? (
              <div className="border border-white/10 bg-black/20 p-3 text-sm text-slate-400">No generated audio yet.</div>
            ) : (
              <div className="grid gap-2">
                {synthesisHistory.map((job) => (
                  <div key={job.id} className={cn(
                    "border p-3",
                    job.status === "failed" ? "border-red-400/30 bg-red-500/10" : "border-white/10 bg-black/20",
                  )}>
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-white">{job.model_name ?? job.model_id}</div>
                        <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-400">
                          <span>{job.text_chars} chars</span>
                          {job.output_bytes ? <span>{(job.output_bytes / 1024).toFixed(1)} KB</span> : null}
                          {job.finished_at ?? job.updated_at ? <span>{formatTimestamp(job.finished_at ?? job.updated_at)}</span> : null}
                          {job.elapsed_seconds != null ? <span>{formatDuration(job.elapsed_seconds)}</span> : null}
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {job.status === "completed" ? (
                          <a
                            className="inline-flex items-center gap-1 border border-emerald-400/30 px-2 py-1 text-xs text-emerald-100 hover:bg-emerald-400/10"
                            href={ttsSynthesisAudioUrl(job.id, true)}
                          >
                            <Download className="h-3.5 w-3.5" />
                            Download
                          </a>
                        ) : null}
                        <button
                          className="border border-white/10 px-2 py-1 text-xs text-slate-200 hover:bg-white/10"
                          onClick={() => void deleteItem("deleteSynthesisJob", job.id)}
                          type="button"
                        >
                          <Trash2 className="inline h-3.5 w-3.5" />
                        </button>
                      </div>
                    </div>
                    <div className="mt-3 border border-white/10 bg-black/20 p-3">
                      <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
                        <span>Text</span>
                        {job.text_source === "recovered_transcript" ? <span>recovered from audio transcript</span> : null}
                      </div>
                      {job.text ? (
                        <p className="whitespace-pre-wrap text-sm leading-6 text-slate-200">{job.text}</p>
                      ) : (
                        <p className="text-sm text-slate-500">Text was not saved for this older audio file.</p>
                      )}
                    </div>
                    {job.status === "completed" ? <audio className="mt-3 w-full" controls src={ttsSynthesisAudioUrl(job.id)} /> : null}
                    {job.error ? <p className="mt-2 text-sm text-red-200">{job.error}</p> : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        </form>
      </SectionCard>


      <SectionCard title="Pocket TTS" description="Fast CPU speech and instant voice cloning while the LLM keeps the GPU.">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
          <span className={cn("border px-2 py-1", pocket.healthy ? "border-emerald-400/30 text-emerald-200" : "border-red-400/30 text-red-200")}>{pocket.healthy ? "online" : "offline"}</span>
          <span className="border border-cyan-400/30 px-2 py-1 text-cyan-100">CPU only</span>
          <span className="text-slate-400">{pocket.modelLoaded ? "model warm" : "cold start on next request"}</span>
        </div>
        {pocket.error ? <p className="mb-3 text-sm text-red-200">{pocket.error}</p> : null}
        <form action={(formData) => void synthesizePocket(formData)} className="grid gap-3">
          <select name="voiceId" required disabled={!pocket.healthy} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60 disabled:opacity-50">
            <option value="">Choose Pocket voice</option>
            {pocket.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name} - {voice.language}{voice.kind === "clone" ? " (clone)" : ""}</option>)}
          </select>
          <textarea name="text" required rows={5} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60" placeholder="Type the text to speak with Pocket TTS." />
          <button disabled={status === "working" || !pocket.healthy} className="inline-flex items-center justify-center gap-2 border border-emerald-400/40 bg-emerald-400/10 px-4 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-400/20 disabled:opacity-50">
            <Play className="h-4 w-4" />Generate With Pocket TTS
          </button>
        </form>
        <details className="mt-4 border border-white/10 bg-black/20 p-3">
          <summary className="cursor-pointer text-sm font-medium text-white">Clone a voice for Pocket TTS</summary>
          <form action={(formData) => void importPocketVoice(formData)} className="mt-3 grid gap-3">
            <input name="name" required className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white" placeholder="voice name" />
            <select name="language" defaultValue="English" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white">
              {['English', 'French', 'German', 'Italian', 'Portuguese', 'Spanish'].map((language) => <option key={language} value={language}>{language}</option>)}
            </select>
            <input name="file" type="file" required accept="audio/*,video/*" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-200 file:mr-3 file:border-0 file:bg-cyan-400/10 file:px-3 file:py-1 file:text-cyan-100" />
            <button disabled={status === "working" || !pocket.healthy} className="inline-flex items-center justify-center gap-2 border border-cyan-400/40 bg-cyan-400/10 px-4 py-2 text-sm text-cyan-100 disabled:opacity-50"><Upload className="h-4 w-4" />Import Pocket Voice</button>
          </form>
          {pocket.voices.some((voice) => voice.kind === "clone") ? <div className="mt-3 grid gap-2">{pocket.voices.filter((voice) => voice.kind === "clone").map((voice) => <div key={voice.id} className="flex items-center justify-between border border-white/10 px-2 py-2 text-sm"><span>{voice.name} - {voice.language}</span><button type="button" aria-label={`Delete ${voice.name}`} className="text-red-200" onClick={() => void deletePocket("deleteVoice", voice.id)}><Trash2 className="h-4 w-4" /></button></div>)}</div> : null}
        </details>
        <div className="mt-4 grid gap-2">
          <div className="flex items-center justify-between"><h3 className="text-sm font-medium text-white">Pocket audio history</h3><span className="text-xs text-slate-400">{pocket.jobs.length} jobs</span></div>
          {pocket.jobs.length === 0 ? <div className="border border-white/10 bg-black/20 p-3 text-sm text-slate-400">No Pocket TTS audio yet.</div> : pocket.jobs.map((job) => (
            <div key={job.id} className={cn("border p-3", job.status === "failed" ? "border-red-400/30 bg-red-500/10" : job.status === "running" || job.status === "queued" ? "border-cyan-400/30 bg-cyan-500/10" : "border-white/10 bg-black/20")}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div><div className="text-sm font-medium text-white">{job.voice_name}</div><div className="text-xs text-slate-400">{job.language} / {job.text_chars} chars / {job.progress_label}</div></div>
                <div className="flex gap-2">{job.status === "completed" ? <a className="border border-emerald-400/30 px-2 py-1 text-xs text-emerald-100" href={`/api/tts/pocket/audio?id=${encodeURIComponent(job.id)}&download=1`}><Download className="inline h-3.5 w-3.5" /> Download</a> : null}{job.status === "completed" || job.status === "failed" ? <button type="button" aria-label="Delete Pocket TTS job" className="border border-red-400/30 px-2 py-1 text-red-100" onClick={() => void deletePocket("deleteJob", job.id)}><Trash2 className="h-3.5 w-3.5" /></button> : null}</div>
              </div>
              {(job.status === "queued" || job.status === "running") ? <div className="mt-3 h-2 border border-white/10 bg-black/30"><div className="h-full bg-cyan-300" style={{ width: `${job.progress_percent}%` }} /></div> : null}
              <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-300">{job.text}</p>
              {job.status === "completed" ? <audio className="mt-3 w-full" controls preload="none" src={`/api/tts/pocket/audio?id=${encodeURIComponent(job.id)}`} /> : null}
              {job.error ? <p className="mt-2 text-sm text-red-200">{job.error}</p> : null}
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Document To Audiobook" description="Use Qwen trained models or Pocket voices with the same sentence-aware chunking, quality checks, preview, stop, resume, and stitching workflow.">
        <form action={(formData) => void createAudiobook(formData)} className="grid gap-3">
          <input type="hidden" name="action" value="createAudiobook" />
          <input name="title" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60" placeholder="optional audiobook title" />
          <select name="engine" value={audiobookEngine} onChange={(event) => setAudiobookEngine(event.target.value as "qwen" | "pocket")} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60">
            <option value="qwen">Qwen3-TTS - GPU trained voice</option>
            <option value="pocket">Pocket TTS - CPU voice</option>
          </select>
          <select name="model_id" required className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60">
            <option value="">{audiobookEngine === "qwen" ? "Choose trained voice model" : "Choose Pocket voice"}</option>
            {audiobookEngine === "qwen"
              ? readyModels.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)
              : pocket.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name} - {voice.language}{voice.kind === "clone" ? " (clone)" : ""}</option>)}
          </select>
          <input
            name="file"
            type="file"
            required
            accept=".epub,.pdf,.docx,.txt,.md,.html,.htm,application/epub+zip,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/*"
            className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-200 file:mr-3 file:border-0 file:bg-cyan-400/10 file:px-3 file:py-1 file:text-cyan-100"
          />
          <button disabled={status === "working" || (audiobookEngine === "qwen" ? readyModels.length === 0 : !pocket.healthy || pocket.voices.length === 0)} className="inline-flex items-center justify-center gap-2 border border-emerald-400/40 bg-emerald-400/10 px-4 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-400/20 disabled:opacity-50">
            <BookOpen className="h-4 w-4" />
            Create Audiobook
          </button>
        </form>
        <div className="mt-4 grid gap-3">
          {audiobookJobs.length === 0 ? <p className="text-sm text-slate-400">No audiobook jobs yet.</p> : null}
          {audiobookJobs.map((job) => {
            const playableChunks = job.chunks.filter((chunk) => chunk.status === "completed" || chunk.status === "flagged");
            const displayChunks = job.chunks;
            const totalChunkPages = Math.max(1, Math.ceil(displayChunks.length / AUDIOBOOK_CHUNKS_PER_PAGE));
            const activeChunkPage = job.current_chunk != null ? Math.floor(job.current_chunk / AUDIOBOOK_CHUNKS_PER_PAGE) : Math.floor(Math.max(0, job.completed_chunks - 1) / AUDIOBOOK_CHUNKS_PER_PAGE);
            const chunkPage = Math.max(0, Math.min(totalChunkPages - 1, audiobookChunkPages[job.id] ?? activeChunkPage));
            const visibleChunks = displayChunks.slice(chunkPage * AUDIOBOOK_CHUNKS_PER_PAGE, (chunkPage + 1) * AUDIOBOOK_CHUNKS_PER_PAGE);
            const audioVersion = `${job.completed_chunks}-${job.updated_at ?? ""}`;
            const canStop = job.status === "queued" || job.status === "running";
            const canResume = job.status === "stopped" || job.status === "failed" || job.status === "needs_review";
            const hasAudio = playableChunks.length > 0;
            const setChunkPage = (page: number) => setAudiobookChunkPages((pages) => ({ ...pages, [job.id]: Math.max(0, Math.min(totalChunkPages - 1, page)) }));
            return (
              <div key={job.id} className={cn("border p-3", job.status === "failed" || job.status === "needs_review" ? "border-amber-400/30 bg-amber-500/10" : "border-white/10 bg-black/20")}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium text-white">{job.title}</div>
                    <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-400">
                      <span>{job.status}</span>
                      <span>{job.completed_chunks}/{job.total_chunks} chunks</span>
                      <span>{job.model_name ?? job.model_id}</span>
                      <span>{job.speech_engine === "pocket" ? "Pocket CPU" : "Qwen GPU"}</span>
                      <span>{job.source_filename}</span>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {canStop ? <button type="button" className="inline-flex items-center gap-1 border border-amber-400/30 px-2 py-1 text-xs text-amber-100 hover:bg-amber-400/10" onClick={() => void controlAudiobook("stopAudiobook", job.id)}><PauseCircle className="h-3.5 w-3.5" />Stop</button> : null}
                    {canResume ? <button type="button" className="inline-flex items-center gap-1 border border-cyan-400/30 px-2 py-1 text-xs text-cyan-100 hover:bg-cyan-400/10" onClick={() => void controlAudiobook("resumeAudiobook", job.id)}><RotateCcw className="h-3.5 w-3.5" />Resume</button> : null}
                    {hasAudio ? <a className="inline-flex items-center gap-1 border border-emerald-400/30 px-2 py-1 text-xs text-emerald-100 hover:bg-emerald-400/10" href={ttsAudiobookAudioUrl(job.id, { download: true, version: audioVersion })}><Download className="h-3.5 w-3.5" />Download</a> : null}
                    {!canStop ? <button type="button" className="border border-red-400/30 px-2 py-1 text-xs text-red-100 hover:bg-red-400/10" onClick={() => void controlAudiobook("deleteAudiobook", job.id)}><Trash2 className="inline h-3.5 w-3.5" /></button> : null}
                  </div>
                </div>
                <div className="mt-3 h-2 border border-white/10 bg-black/30">
                  <div className="h-full bg-emerald-300 transition-all" style={{ width: `${audiobookProgressValue(job)}%` }} />
                </div>
                <div className="mt-1 flex flex-wrap justify-between gap-2 text-xs text-slate-400"><span>{job.progress_label}</span><span className="flex items-center gap-3"><span>{audiobookProgressValue(job).toFixed(1)}%</span>{canStop ? <span className="inline-flex items-center gap-1 text-cyan-200"><Clock className="h-3.5 w-3.5" />ETA {formatEta(job.eta_seconds, true)}</span> : null}</span></div>
                {job.error ? <p className="mt-2 text-sm text-red-200">{job.error}</p> : null}
                {hasAudio ? <audio className="mt-3 w-full" controls src={ttsAudiobookAudioUrl(job.id, { version: audioVersion })} /> : null}
                {hasAudio ? (
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border border-white/10 bg-black/20 px-2 py-2 text-xs text-slate-300">
                    <span>
                      Showing chunks {chunkPage * AUDIOBOOK_CHUNKS_PER_PAGE + 1}-{Math.min(displayChunks.length, (chunkPage + 1) * AUDIOBOOK_CHUNKS_PER_PAGE)} of {displayChunks.length}
                    </span>
                    <div className="flex flex-wrap gap-2">
                      <button type="button" disabled={chunkPage === 0} className="border border-white/10 px-2 py-1 text-slate-200 hover:bg-white/10 disabled:opacity-40" onClick={() => setChunkPage(chunkPage - 1)}>Prev</button>
                      <button type="button" disabled={chunkPage >= totalChunkPages - 1} className="border border-white/10 px-2 py-1 text-slate-200 hover:bg-white/10 disabled:opacity-40" onClick={() => setChunkPage(chunkPage + 1)}>Next</button>
                      <button type="button" disabled={chunkPage >= totalChunkPages - 1} className="border border-cyan-400/30 px-2 py-1 text-cyan-100 hover:bg-cyan-400/10 disabled:opacity-40" onClick={() => setChunkPage(totalChunkPages - 1)}>Latest</button>
                    </div>
                  </div>
                ) : null}
                <div className="mt-3 grid gap-2 md:grid-cols-2">
                  {visibleChunks.map((chunk) => {
                    const canRegenerate = chunk.status !== "skipped" && chunk.role !== "skipped_front_matter" && Boolean(chunk.text?.trim());
                    const hasChunkAudio = chunk.status === "completed" || chunk.status === "flagged";
                    return (
                      <div key={chunk.index} className={cn("border p-2", chunk.status === "flagged" ? "border-amber-400/30 bg-amber-500/10" : chunk.status === "running" ? "border-cyan-400/30 bg-cyan-500/10" : "border-white/10 bg-black/20")}>
                        <div className="flex items-center justify-between gap-2 text-xs text-slate-300">
                          <span>Chunk {chunk.index + 1}</span>
                          <div className="flex items-center gap-2">
                            <span>{chunk.regenerate_requested ? "queued refresh" : chunk.quality?.duration_seconds ? `${chunk.quality.duration_seconds}s` : chunk.status}</span>
                            <button
                              type="button"
                              title="Regenerate this chunk"
                              aria-label={`Regenerate chunk ${chunk.index + 1}`}
                              disabled={!canRegenerate || status === "working"}
                              className="inline-flex h-7 w-7 items-center justify-center border border-cyan-400/30 text-cyan-100 hover:bg-cyan-400/10 disabled:cursor-not-allowed disabled:opacity-35"
                              onClick={() => void regenerateAudiobookChunk(job.id, chunk.index)}
                            >
                              <RefreshCw className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                        {chunk.quality?.ok === false ? <p className="mt-1 text-xs text-amber-200">Flagged: {chunk.quality.reasons?.join(", ")}</p> : null}
                        {chunk.error ? <p className="mt-1 text-xs text-red-200">{chunk.error}</p> : null}
                        {chunk.status === "skipped" ? <p className="mt-2 text-xs text-slate-500">{chunk.skipped_reason ?? "Skipped"}</p> : null}
                        {hasChunkAudio ? <audio className="mt-2 w-full" controls src={ttsAudiobookAudioUrl(job.id, { chunk: chunk.index, version: `${audioVersion}-${chunk.updated_at ?? ""}` })} /> : null}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </SectionCard>

      <SectionCard title="PowerPoint Narration" description="Upload a PPTX with speaker notes and narrate it with either a Qwen trained model or a Pocket voice.">
        <form action={(formData) => void createPresentation(formData)} className="grid gap-3">
          <input type="hidden" name="action" value="createPresentation" />
          <input name="title" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60" placeholder="optional narrated deck title" />
          <select name="engine" value={presentationEngine} onChange={(event) => setPresentationEngine(event.target.value as "qwen" | "pocket")} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60">
            <option value="qwen">Qwen3-TTS - GPU trained voice</option>
            <option value="pocket">Pocket TTS - CPU voice</option>
          </select>
          <select name="model_id" required className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60">
            <option value="">{presentationEngine === "qwen" ? "Choose trained voice model" : "Choose Pocket voice"}</option>
            {presentationEngine === "qwen"
              ? readyModels.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)
              : pocket.voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.name} - {voice.language}{voice.kind === "clone" ? " (clone)" : ""}</option>)}
          </select>
          <input
            name="file"
            type="file"
            required
            accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation"
            className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-slate-200 file:mr-3 file:border-0 file:bg-cyan-400/10 file:px-3 file:py-1 file:text-cyan-100"
          />
          <button disabled={status === "working" || (presentationEngine === "qwen" ? readyModels.length === 0 : !pocket.healthy || pocket.voices.length === 0)} className="inline-flex items-center justify-center gap-2 border border-violet-400/40 bg-violet-400/10 px-4 py-2 text-sm font-medium text-violet-100 hover:bg-violet-400/20 disabled:opacity-50">
            <Upload className="h-4 w-4" />
            Create Narrated PPTX
          </button>
          <p className="text-xs text-slate-500">V1 accepts .pptx only. Save legacy .ppt files as .pptx before uploading.</p>
        </form>
        <div className="mt-4 grid gap-3">
          {presentationJobs.length === 0 ? <p className="text-sm text-slate-400">No narrated PowerPoint jobs yet.</p> : null}
          {presentationJobs.map((job) => {
            const narratedSlides = job.slides.filter((slide) => slide.status === "completed" || slide.status === "flagged");
            const canStop = job.status === "queued" || job.status === "running";
            const canResume = job.status === "stopped" || job.status === "failed" || job.status === "needs_review" || job.status === "paused";
            const hasOutput = Boolean(job.output_path || job.output_bytes || narratedSlides.length > 0);
            const version = `${job.completed_slides}-${job.updated_at ?? ""}`;
            return (
              <div key={job.id} className={cn("border p-3", job.status === "failed" || job.status === "needs_review" ? "border-amber-400/30 bg-amber-500/10" : "border-white/10 bg-black/20")}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium text-white">{job.title}</div>
                    <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-400">
                      <span>{job.status}</span>
                      <span>{job.completed_slides}/{job.total_slides} slides</span>
                      <span>{job.narration_slides} narrated</span>
                      <span>{job.model_name ?? job.model_id}</span>
                      <span>{job.source_filename}</span>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {canStop ? <button type="button" className="inline-flex items-center gap-1 border border-amber-400/30 px-2 py-1 text-xs text-amber-100 hover:bg-amber-400/10" onClick={() => void controlPresentation("stopPresentation", job.id)}><PauseCircle className="h-3.5 w-3.5" />Stop</button> : null}
                    {canResume ? <button type="button" className="inline-flex items-center gap-1 border border-cyan-400/30 px-2 py-1 text-xs text-cyan-100 hover:bg-cyan-400/10" onClick={() => void controlPresentation("resumePresentation", job.id)}><RotateCcw className="h-3.5 w-3.5" />Resume</button> : null}
                    {hasOutput ? <a className="inline-flex items-center gap-1 border border-emerald-400/30 px-2 py-1 text-xs text-emerald-100 hover:bg-emerald-400/10" href={ttsPresentationOutputUrl(job.id, { download: true, version })}><Download className="h-3.5 w-3.5" />PPTX</a> : null}
                    {!canStop ? <button type="button" className="border border-red-400/30 px-2 py-1 text-xs text-red-100 hover:bg-red-400/10" onClick={() => void controlPresentation("deletePresentation", job.id)}><Trash2 className="inline h-3.5 w-3.5" /></button> : null}
                  </div>
                </div>
                <div className="mt-3 h-2 border border-white/10 bg-black/30">
                  <div className="h-full bg-violet-300 transition-all" style={{ width: `${presentationProgressValue(job)}%` }} />
                </div>
                <div className="mt-1 flex flex-wrap justify-between gap-2 text-xs text-slate-400"><span>{job.progress_label}</span><span className="flex items-center gap-3"><span>{presentationProgressValue(job).toFixed(1)}%</span>{canStop ? <span className="inline-flex items-center gap-1 text-violet-200"><Clock className="h-3.5 w-3.5" />ETA {formatEta(job.eta_seconds, true)}</span> : null}</span></div>
                {job.error ? <p className="mt-2 text-sm text-red-200">{job.error}</p> : null}
                {narratedSlides.length > 0 ? (
                  <div className="mt-3 grid gap-2 md:grid-cols-2">
                    {narratedSlides.map((slide) => (
                      <div key={slide.index} className={cn("border p-2", slide.status === "flagged" ? "border-amber-400/30 bg-amber-500/10" : "border-white/10 bg-black/20")}>
                        <div className="flex items-center justify-between gap-2 text-xs text-slate-300">
                          <span>Slide {slide.slide_number}</span>
                          <span>{slide.audio_duration_seconds ? `${slide.audio_duration_seconds}s` : slide.status}</span>
                        </div>
                        {slide.quality?.ok === false ? <p className="mt-1 text-xs text-amber-200">Flagged: {slide.quality.reasons?.join(", ")}</p> : null}
                        <audio className="mt-2 w-full" controls src={ttsPresentationSlideAudioUrl(job.id, slide.index, { version })} />
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </SectionCard>


      <SectionCard title="Voices" description="Prompt-designed reference voices.">
        <div className="grid gap-3">
          {snapshot.voiceJobs.filter((job) => job.status === "queued" || job.status === "running" || job.status === "failed").slice().reverse().map((job) => (
            <div key={job.id} className={cn("border p-3", job.status === "failed" ? "border-red-400/30 bg-red-500/10" : "border-cyan-400/30 bg-cyan-500/10")}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-medium text-white">{job.name || `voice_${job.id.slice(0, 8)}`}</div>
                  <div className="text-xs text-slate-400">{job.status} / {job.device} / {job.progress_label}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-300">
                  <div className="flex items-center gap-2">
                    <Clock className="h-3.5 w-3.5" />
                    <span>elapsed {formatDuration(job.elapsed_seconds)}</span>
                    <span>ETA {formatDuration(job.eta_seconds)}</span>
                  </div>
                  {job.status === "failed" ? (
                    <button className="border border-red-400/30 px-2 py-1 text-xs text-red-100 hover:bg-red-400/10" onClick={() => void deleteItem("deleteVoiceJob", job.id)}>
                      <Trash2 className="inline h-3.5 w-3.5" />
                    </button>
                  ) : null}
                </div>
              </div>
              <div className="mt-3 h-2 border border-white/10 bg-black/30">
                <div className="h-full bg-cyan-300 transition-all" style={{ width: `${progressValue(job)}%` }} />
              </div>
              <div className="mt-1 text-right text-xs text-slate-300">{progressValue(job).toFixed(1)}%</div>
              {job.error ? <p className="mt-2 text-sm text-red-200">{job.error}</p> : null}
            </div>
          ))}
          {snapshot.voices.length === 0 ? <p className="text-sm text-slate-400">No voices yet.</p> : null}
          {snapshot.voices.map((voice) => (
            <div key={voice.id} className="border border-white/10 bg-black/20 p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-white">{voice.name}</div>
                  <div className="text-xs text-slate-500">{voice.language} / {voice.source === "upload" ? "uploaded media" : voice.device || "device unknown"} / {voice.created_at}</div>
                </div>
                <div className="flex gap-2">
                  <button className="border border-cyan-400/30 px-2 py-1 text-xs text-cyan-100 hover:bg-cyan-400/10" onClick={() => void trainModel(voice)}>
                    <Sparkles className="inline h-3.5 w-3.5" /> Train
                  </button>
                  <button className="border border-red-400/30 px-2 py-1 text-xs text-red-100 hover:bg-red-400/10" onClick={() => void deleteItem("deleteVoice", voice.id)}>
                    <Trash2 className="inline h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
              <p className="mt-2 text-sm text-slate-300">{voice.instruct}</p>
              {voice.paragraph_text ? (
                <p className="mt-2 max-h-20 overflow-hidden text-sm text-slate-400">{voice.paragraph_text}</p>
              ) : null}
              <audio className="mt-3 w-full" controls src={ttsSampleUrl("voices", voice.id)} />
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Trained Voice Models" description="Consistent cloned voices trained from reference voices.">
        <div className="grid gap-3">
          {snapshot.models.length === 0 ? <p className="text-sm text-slate-400">No trained models yet.</p> : null}
          {snapshot.models.map((model: TtsModel) => (
            <div key={model.id} className={cn("border p-3", model.status === "failed" ? "border-red-400/30 bg-red-500/10" : model.status === "training" ? "border-cyan-400/30 bg-cyan-500/10" : "border-white/10 bg-black/20")}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-white">{model.name}</div>
                  <div className="text-xs text-slate-500">{model.status} / {model.progress_label || "ready"} / {model.created_at}</div>
                  {model.status === "training" ? (
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-300">
                      <Clock className="h-3.5 w-3.5" />
                      <span>elapsed {formatDuration(model.elapsed_seconds)}</span>
                      <span>ETA {formatDuration(model.eta_seconds)}</span>
                    </div>
                  ) : null}
                </div>
                <button className="border border-red-400/30 px-2 py-1 text-xs text-red-100 hover:bg-red-400/10" onClick={() => void deleteItem("deleteModel", model.id)}>
                  <Trash2 className="inline h-3.5 w-3.5" />
                </button>
              </div>
              {model.status === "training" || model.status === "failed" ? (
                <>
                  <div className="mt-3 h-2 border border-white/10 bg-black/30">
                    <div className={cn("h-full transition-all", model.status === "failed" ? "bg-red-300" : "bg-cyan-300")} style={{ width: `${modelProgressValue(model)}%` }} />
                  </div>
                  <div className="mt-1 text-right text-xs text-slate-300">{modelProgressValue(model).toFixed(1)}%</div>
                </>
              ) : null}
              {model.error ? <pre className="mt-2 max-h-44 overflow-auto whitespace-pre-wrap border border-red-400/20 bg-black/30 p-2 text-xs text-red-200">{model.error}</pre> : null}
              {model.status === "ready" ? <audio className="mt-3 w-full" controls src={ttsSampleUrl("models", model.id)} /> : null}
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
