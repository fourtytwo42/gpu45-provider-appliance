"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Clock, Download, Mic2, Play, RefreshCw, Sparkles, Trash2, Upload, Wand2 } from "lucide-react";
import { SectionCard } from "./section-card";
import type { TtsModel, TtsSnapshot, TtsSynthesisJob, TtsVoice, TtsVoiceJob } from "@/lib/tts";
import { ttsSampleUrl, ttsSynthesisAudioUrl } from "@/lib/tts";
import { cn } from "@/lib/cn";

type Status = "idle" | "working" | "error";

async function parseJson(response: Response): Promise<Record<string, unknown>> {
  const json = await response.json() as Record<string, unknown>;
  if (!response.ok) throw new Error(String(json.error ?? json.detail ?? "TTS request failed"));
  return json;
}

function formatDuration(seconds?: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "unknown";
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
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

export function TtsConsole({ initialSnapshot }: { initialSnapshot: TtsSnapshot }) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState("");
  const [activeSynthesisId, setActiveSynthesisId] = useState<string | null>(null);
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
    if (activeSynthesisJobs.length === 0) return undefined;
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [activeSynthesisJobs.length, refresh]);

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
