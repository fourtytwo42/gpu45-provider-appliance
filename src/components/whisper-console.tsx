"use client";

import { useEffect, useMemo, useState } from "react";
import { Download, FileAudio, FileText, RefreshCw, Trash2, Upload } from "lucide-react";
import { SectionCard } from "./section-card";
import { cn } from "@/lib/cn";
import type { WhisperJob, WhisperSnapshot } from "@/lib/whisper";
import { WHISPER_MODELS, whisperTranscriptUrl } from "@/lib/whisper";
import { subscribeApplianceEvent } from "@/lib/appliance-events";

type Status = "idle" | "working" | "error";

async function parseJson(response: Response): Promise<Record<string, unknown>> {
  const json = await response.json() as Record<string, unknown>;
  if (!response.ok) throw new Error(String(json.error ?? json.detail ?? "Whisper request failed"));
  return json;
}

function statusLabel(job: WhisperJob): string {
  if (job.status === "completed") return "Transcript ready";
  if (job.status === "running") return "Transcribing";
  if (job.status === "queued") return "Queued";
  return job.error ?? "Failed";
}

function formatDuration(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || !Number.isFinite(seconds)) return "n/a";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${secs}s`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

function progressPercent(job: WhisperJob): number {
  if (job.status === "completed" || job.status === "failed") return 100;
  return Math.max(0, Math.min(100, job.progress_percent ?? (job.status === "running" ? 2 : 0)));
}

export function WhisperConsole({ initialSnapshot }: { initialSnapshot: WhisperSnapshot }) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState("");
  const models = useMemo(() => snapshot.models.length > 0 ? snapshot.models : WHISPER_MODELS, [snapshot.models]);

  async function refresh(): Promise<void> {
    const response = await fetch("/api/whisper", { cache: "no-store" });
    const next = await response.json() as WhisperSnapshot;
    setSnapshot(next);
  }

  useEffect(() => {
    return subscribeApplianceEvent<WhisperSnapshot>("whisper", setSnapshot);
  }, []);

  async function submit(formData: FormData): Promise<void> {
    setStatus("working");
    setMessage("Uploading file and queueing transcription.");
    try {
      const response = await fetch("/api/whisper", { method: "POST", body: formData });
      await parseJson(response);
      setMessage("Transcription queued. The job list refreshes automatically.");
      setStatus("idle");
      await refresh();
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "Transcription failed");
    }
  }

  async function deleteJob(id: string): Promise<void> {
    setStatus("working");
    setMessage("Deleting transcript job and files.");
    try {
      const response = await fetch("/api/whisper", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "deleteJob", id }),
      });
      await parseJson(response);
      setStatus("idle");
      setMessage("Deleted.");
      await refresh();
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "Delete failed");
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(420px,0.8fr)_minmax(0,1.2fr)]">
      <section className="xl:col-span-2">
        <div className="flex flex-wrap items-center justify-between gap-3 border border-white/10 bg-[#07121a] px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center border border-cyan-400/40 bg-cyan-400/10 text-cyan-200">
              <FileText className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-white">Whisper Transcription</h1>
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

      <SectionCard title="New Transcript" description="Upload audio or video. Output is saved as a Markdown transcript.">
        <form action={(formData) => void submit(formData)} className="grid gap-3">
          <label className="grid gap-2 text-sm text-slate-300">
            Media file
            <input
              name="file"
              type="file"
              required
              accept="audio/*,video/*,.m4a,.mp3,.wav,.flac,.ogg,.mp4,.mov,.mkv,.webm"
              className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white file:mr-3 file:border-0 file:bg-cyan-400/10 file:px-3 file:py-1.5 file:text-cyan-100"
            />
          </label>
          <label className="grid gap-2 text-sm text-slate-300">
            Model size
            <select name="model" defaultValue="small" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60">
              {models.map((model) => <option key={model} value={model}>{model}</option>)}
            </select>
          </label>
          <label className="grid gap-2 text-sm text-slate-300">
            Task
            <select name="task" defaultValue="transcribe" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60">
              <option value="transcribe">Transcribe original language</option>
              <option value="translate">Translate to English</option>
            </select>
          </label>
          <label className="grid gap-2 text-sm text-slate-300">
            Language hint
            <input name="language" placeholder="optional, e.g. en" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-400/60" />
          </label>
          <button disabled={status === "working"} className="inline-flex items-center justify-center gap-2 border border-emerald-400/40 bg-emerald-400/10 px-4 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-400/20 disabled:opacity-50">
            <Upload className="h-4 w-4" />
            Create Transcript
          </button>
        </form>
      </SectionCard>

      <SectionCard title="Transcript Jobs" description="Completed jobs include Markdown transcript downloads.">
        <div className="grid gap-3 md:grid-cols-2">
          {snapshot.jobs.length === 0 ? <p className="text-sm text-slate-400">No transcript jobs yet.</p> : null}
          {snapshot.jobs.map((job) => (
            <article key={job.id} className="border border-white/10 bg-black/20 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-medium text-white">
                    <FileAudio className="h-4 w-4 shrink-0 text-cyan-200" />
                    <span className="truncate">{job.filename}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{job.model} / {job.task} / {job.created_at}</div>
                </div>
                <span className={cn("shrink-0 border px-2 py-1 text-xs", job.status === "completed" ? "border-emerald-400/40 text-emerald-200" : job.status === "failed" ? "border-red-400/40 text-red-200" : "border-cyan-400/40 text-cyan-200")}>
                  {job.status}
                </span>
              </div>
              <p className="mt-3 text-sm text-slate-300">{statusLabel(job)}</p>
              {job.status === "running" || job.status === "queued" ? (
                <div className="mt-3 grid gap-2">
                  <div className="flex items-center justify-between gap-3 text-xs text-slate-400">
                    <span>{job.progress_label ?? statusLabel(job)}</span>
                    <span>{Math.round(progressPercent(job))}%</span>
                  </div>
                  <div className="h-2 overflow-hidden border border-white/10 bg-black/40">
                    <div className="h-full bg-cyan-400 transition-all" style={{ width: `${progressPercent(job)}%` }} />
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-500">
                    <div className="border border-white/10 bg-white/[0.03] px-2 py-1">ETA {formatDuration(job.eta_seconds)}</div>
                    <div className="border border-white/10 bg-white/[0.03] px-2 py-1">
                      {formatDuration(job.processed_seconds)} / {formatDuration(job.media_duration_seconds)}
                    </div>
                  </div>
                </div>
              ) : null}
              {job.status === "completed" ? (
                <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-500">
                  <div className="border border-white/10 bg-white/[0.03] px-2 py-1">Runtime {formatDuration(job.duration_seconds)}</div>
                  <div className="border border-white/10 bg-white/[0.03] px-2 py-1">Media {formatDuration(job.media_duration_seconds)}</div>
                </div>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                {job.status === "completed" ? (
                  <a className="inline-flex items-center gap-2 border border-cyan-400/30 px-3 py-1.5 text-sm text-cyan-100 hover:bg-cyan-400/10" href={whisperTranscriptUrl(job.id)}>
                    <Download className="h-4 w-4" />
                    Markdown
                  </a>
                ) : null}
                <button className="inline-flex items-center gap-2 border border-red-400/30 px-3 py-1.5 text-sm text-red-100 hover:bg-red-400/10" onClick={() => void deleteJob(job.id)}>
                  <Trash2 className="h-4 w-4" />
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
