"use client";

import { useEffect, useMemo, useState } from "react";
import { Download, Film, Loader2, RefreshCw, Square, Trash2, Wand2 } from "lucide-react";
import { SectionCard } from "./section-card";
import { cn } from "@/lib/cn";
import type { VideoJob, VideoProfile, VideoSnapshot } from "@/lib/video";
import { videoOutputUrl } from "@/lib/video";

type RunState = "idle" | "working" | "error";
const DEFAULT_NEGATIVE_PROMPT = "abstract colors, smoke only, overexposed, blown out highlights, blurry, low quality, distorted subject, missing subject, text, watermark, painting, cartoon";
const VIDEO_PRESETS = {
  preview: { label: "Preview", size: "832*480", steps: 8, duration: 2 },
  balanced: { label: "Balanced", size: "832*480", steps: 12, duration: 2 },
  quality: { label: "Quality", size: "832*480", steps: 16, duration: 2 },
  custom: { label: "Custom", size: "832*480", steps: 8, duration: 2 },
};

async function parseJson(response: Response): Promise<Record<string, unknown>> {
  const data = await response.json() as Record<string, unknown>;
  if (!response.ok) throw new Error(String(data.error ?? "Video request failed"));
  return data;
}

export function VideoConsole({ initialSnapshot }: { initialSnapshot: VideoSnapshot }) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [state, setState] = useState<RunState>("idle");
  const [message, setMessage] = useState("");
  const [selectedProfile, setSelectedProfile] = useState(initialSnapshot.profiles[0]?.id ?? "wan22-ti2v-5b");
  const [preset, setPreset] = useState<keyof typeof VIDEO_PRESETS>("preview");
  const [size, setSize] = useState(VIDEO_PRESETS.preview.size);
  const [steps, setSteps] = useState(VIDEO_PRESETS.preview.steps);
  const [duration, setDuration] = useState(VIDEO_PRESETS.preview.duration);
  const activeJob = useMemo(() => snapshot.jobs.find((job) => job.status === "running" || job.status === "queued"), [snapshot.jobs]);
  const selectedProfileInfo = useMemo(() => snapshot.profiles.find((profile) => profile.id === selectedProfile), [selectedProfile, snapshot.profiles]);

  async function refresh(): Promise<void> {
    const response = await fetch("/api/video", { cache: "no-store" });
    setSnapshot(await response.json() as VideoSnapshot);
  }

  async function run(action: () => Promise<void>, working: string): Promise<void> {
    setState("working");
    setMessage(working);
    try {
      await action();
      await refresh();
      setState("idle");
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "Video action failed");
    }
  }

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refresh().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  async function downloadModel(profile: string): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "downloadModel", profile }),
      });
      await parseJson(response);
      setMessage("Model download started. This is large and can take a while.");
    }, "Starting video model download.");
  }

  async function createJob(formData: FormData): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "createJob",
          profile: formData.get("profile"),
          prompt: formData.get("prompt"),
          negative_prompt: formData.get("negative_prompt"),
          size,
          steps,
          duration_seconds: duration,
          seed: Number(formData.get("seed") || -1),
        }),
      });
      await parseJson(response);
      setMessage("Video job queued. The LLM will be stopped while Wan uses the GPU.");
    }, "Queueing video generation job.");
  }

  async function deleteJob(id: string): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "deleteJob", id }),
      });
      await parseJson(response);
      setMessage("Video job deleted.");
    }, "Deleting video job.");
  }

  async function cancelJob(id: string): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "cancelJob", id }),
      });
      await parseJson(response);
      setMessage("Video job cancelled.");
    }, "Cancelling video job.");
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(460px,1.05fr)]">
      <section className="xl:col-span-2">
        <div className="flex flex-wrap items-center justify-between gap-3 border border-white/10 bg-[#07121a] px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center border border-fuchsia-400/40 bg-fuchsia-400/10 text-fuchsia-200">
              <Film className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-white">Wan2.2 Video Lab</h1>
              <p className="text-sm text-slate-400">{snapshot.serviceUrl}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={cn("border px-3 py-1 text-sm", snapshot.healthy ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-red-400/40 bg-red-400/10 text-red-200")}>
              {snapshot.healthy ? "online" : "offline"}
            </span>
            <span className={cn("border px-3 py-1 text-sm", snapshot.modelReady ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-200" : "border-amber-400/40 bg-amber-400/10 text-amber-200")}>
              {snapshot.modelReady ? "model ready" : "model missing"}
            </span>
            <button className="inline-flex items-center gap-2 border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 hover:bg-white/10" onClick={() => void refresh()}>
              <RefreshCw className="h-4 w-4" />
              Refresh
            </button>
          </div>
        </div>
        {message ? (
          <div className={cn("mt-3 border px-4 py-3 text-sm", state === "error" ? "border-red-400/30 bg-red-500/10 text-red-200" : "border-fuchsia-400/30 bg-fuchsia-500/10 text-fuchsia-100")}>
            {state === "working" ? "Working: " : null}{message}
          </div>
        ) : null}
        {!snapshot.healthy && snapshot.error ? <div className="mt-3 border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{snapshot.error}</div> : null}
      </section>

      <SectionCard title="Generate" description="Wan uses the GPU. The service stops the LLM during a generation job and restarts it afterward.">
        <form action={(formData) => void createJob(formData)} className="grid gap-3">
          <label className="grid gap-1 text-xs text-slate-400">
            Model
            <select
              name="profile"
              value={selectedProfile}
              onChange={(event) => setSelectedProfile(event.target.value)}
              className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none"
            >
              {snapshot.profiles.map((profile) => (
                <option key={profile.id} value={profile.id}>{profile.name}{profile.ready ? "" : " (not installed)"}</option>
              ))}
            </select>
          </label>
          {selectedProfileInfo ? (
            <div className={cn("border px-3 py-2 text-xs", selectedProfileInfo.ready ? "border-cyan-400/30 bg-cyan-400/10 text-cyan-100" : "border-amber-400/30 bg-amber-400/10 text-amber-100")}>
              {selectedProfileInfo.description}
            </div>
          ) : null}
          <textarea
            name="prompt"
            required
            rows={7}
            className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-fuchsia-400/60"
            placeholder="A cinematic close-up of a compact AI appliance in a dark rack, status lights pulsing softly, shallow depth of field, realistic motion."
          />
          <textarea
            name="negative_prompt"
            rows={3}
            className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-fuchsia-400/60"
            placeholder="blur, artifacts, watermark, low quality"
            defaultValue={DEFAULT_NEGATIVE_PROMPT}
          />
          <div className="grid gap-3 sm:grid-cols-4">
            <label className="grid gap-1 text-xs text-slate-400">
              Preset
              <select
                value={preset}
                onChange={(event) => {
                  const nextPreset = event.target.value as keyof typeof VIDEO_PRESETS;
                  const values = VIDEO_PRESETS[nextPreset];
                  setPreset(nextPreset);
                  setSize(values.size);
                  setSteps(values.steps);
                  setDuration(values.duration);
                }}
                className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none"
              >
                <option value="preview">Preview - fastest usable</option>
                <option value="balanced">Balanced</option>
                <option value="quality">Quality</option>
                <option value="custom">Custom</option>
              </select>
            </label>
            <label className="grid gap-1 text-xs text-slate-400">
              Size
              <select
                name="size"
                value={size}
                onChange={(event) => { setSize(event.target.value); setPreset("custom"); }}
                className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none"
              >
                <option value="832*480">832x480</option>
                <option value="480*832">480x832</option>
                <option value="1280*704">1280x704</option>
                <option value="704*1280">704x1280</option>
              </select>
            </label>
            <label className="grid gap-1 text-xs text-slate-400">
              Steps
              <input
                name="steps"
                type="number"
                min={1}
                max={24}
                value={steps}
                onChange={(event) => { setSteps(Number(event.target.value)); setPreset("custom"); }}
                className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none"
              />
            </label>
            <label className="grid gap-1 text-xs text-slate-400">
              Duration
              <select
                name="duration_seconds"
                value={duration}
                onChange={(event) => { setDuration(Number(event.target.value)); setPreset("custom"); }}
                className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none"
              >
                {Array.from({ length: 14 }, (_, index) => index + 2).map((seconds) => (
                  <option key={seconds} value={seconds}>{seconds}s</option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-xs text-slate-400">
              Seed
              <input name="seed" type="number" defaultValue={-1} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none" />
            </label>
          </div>
          <button disabled={state === "working" || Boolean(activeJob) || !selectedProfileInfo?.ready} className="inline-flex items-center justify-center gap-2 border border-fuchsia-400/40 bg-fuchsia-400/10 px-4 py-2 text-sm font-medium text-fuchsia-100 hover:bg-fuchsia-400/20 disabled:opacity-50">
            <Wand2 className="h-4 w-4" />
            Queue Video
          </button>
        </form>
      </SectionCard>

      <SectionCard title="Models" description="Only profiles verified on this appliance are exposed here.">
        <div className="grid gap-3 text-sm text-slate-300">
          {snapshot.profiles.map((profile: VideoProfile) => (
            <div key={profile.id} className="grid gap-3 border border-white/10 bg-black/20 p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-white">{profile.name}</div>
                  <div className="mt-1 text-xs text-slate-500">{profile.repo}</div>
                </div>
                <span className={cn("border px-2 py-1 text-xs", profile.ready ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-amber-400/40 bg-amber-400/10 text-amber-200")}>
                  {profile.ready ? "installed" : "missing"}
                </span>
              </div>
              <div>{profile.description}</div>
              <button disabled={state === "working" || profile.ready} className="inline-flex items-center justify-center gap-2 border border-cyan-400/40 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-400/20 disabled:opacity-50" onClick={() => void downloadModel(profile.id)}>
                <Download className="h-4 w-4" />
                {profile.ready ? "Model Installed" : "Download Model"}
              </button>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Jobs" className="xl:col-span-2">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {snapshot.jobs.length === 0 ? <p className="text-sm text-slate-400">No video jobs yet.</p> : null}
          {snapshot.jobs.map((job: VideoJob) => (
            <div key={job.id} className="overflow-hidden border border-white/10 bg-black/20">
              <div className="aspect-video border-b border-white/10 bg-black/30">
                {job.status === "completed" ? (
                  <video className="h-full w-full object-contain" controls src={videoOutputUrl(job.id)} />
                ) : (
                  <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 p-4 text-center text-sm text-slate-500">
                    {(job.status === "running" || job.status === "queued") ? <Loader2 className="h-5 w-5 animate-spin text-fuchsia-200" /> : null}
                    <span>{job.status === "failed" ? "Generation failed" : job.status === "cancelled" ? "Cancelled" : "Waiting for output"}</span>
                  </div>
                )}
              </div>
              <div className="grid gap-2 p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cn("border px-2 py-0.5 text-xs", job.status === "completed" ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : job.status === "failed" ? "border-red-400/40 bg-red-400/10 text-red-200" : "border-fuchsia-400/40 bg-fuchsia-400/10 text-fuchsia-200")}>
                        {job.status}
                      </span>
                      <span className="truncate text-xs text-slate-500">{job.profile_name ?? job.profile ?? "Wan"}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={state === "working" || job.status === "running"}
                    title={job.status === "running" ? "Running jobs cannot be deleted yet" : "Delete job and files"}
                    className="inline-flex h-8 w-8 shrink-0 items-center justify-center border border-red-400/30 bg-red-500/10 text-red-200 hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={() => void deleteJob(job.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                {(job.status === "running" || job.status === "queued") ? (
                  <button
                    type="button"
                    disabled={state === "working"}
                    className="inline-flex items-center justify-center gap-2 border border-amber-400/40 bg-amber-400/10 px-3 py-1.5 text-xs font-medium text-amber-100 hover:bg-amber-400/20 disabled:opacity-50"
                    onClick={() => void cancelJob(job.id)}
                  >
                    <Square className="h-3.5 w-3.5" />
                    Cancel Generation
                  </button>
                ) : null}
                <p className="line-clamp-2 min-h-10 text-sm text-slate-200">{job.prompt}</p>
                <div className="grid grid-cols-4 gap-2 text-center text-[11px] text-slate-400">
                  <div className="border border-white/10 bg-white/[0.03] px-1 py-1">{job.size}</div>
                  <div className="border border-white/10 bg-white/[0.03] px-1 py-1">{job.duration_seconds ?? 5}s</div>
                  <div className="border border-white/10 bg-white/[0.03] px-1 py-1">{job.steps} steps</div>
                  <div className="border border-white/10 bg-white/[0.03] px-1 py-1">seed {job.seed}</div>
                </div>
                {(job.status === "running" || job.status === "queued") ? (
                  <div className="grid gap-1">
                    <div className="flex items-center justify-between gap-2 text-xs text-slate-400">
                      <span>{job.progress_label ?? (job.status === "queued" ? "Queued" : "Working")}</span>
                      <span>{Math.round(job.progress_percent ?? 0)}%</span>
                    </div>
                    <div className="h-2 overflow-hidden bg-white/10">
                      <div
                        className="h-full bg-fuchsia-300 transition-all duration-500"
                        style={{ width: `${Math.max(0, Math.min(100, job.progress_percent ?? 0))}%` }}
                      />
                    </div>
                  </div>
                ) : null}
                {job.error ? <div className="line-clamp-2 border border-red-400/30 bg-red-500/10 px-2 py-1 text-xs text-red-100">{job.error}</div> : null}
              </div>
            </div>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
