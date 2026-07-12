"use client";

import { useEffect, useMemo, useState } from "react";
import { Download, ImageIcon, RefreshCw, Trash2, Wand2 } from "lucide-react";
import { SectionCard } from "./section-card";
import { cn } from "@/lib/cn";
import type { ImageJob, ImageProfile, ImageSnapshot } from "@/lib/images";
import { imageOutputUrl } from "@/lib/images";
import { subscribeApplianceEvent } from "@/lib/appliance-events";

type RunState = "idle" | "working" | "error";

async function parseJson(response: Response): Promise<Record<string, unknown>> {
  const text = await response.text();
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(text) as Record<string, unknown>;
  } catch {
    throw new Error(`Image request returned ${response.status} ${response.statusText || "without JSON"}.`);
  }
  if (!response.ok) throw new Error(String(data.error ?? "Image request failed"));
  return data;
}

function metric(value: number | null | undefined, suffix: string): string {
  return typeof value === "number" ? `${value}${suffix}` : "n/a";
}

function formatEta(seconds: number | null | undefined): string {
  if (typeof seconds !== "number") return "eta n/a";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s left`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder.toString().padStart(2, "0")}s left`;
}

function progressValue(job: ImageJob): number | null {
  if (typeof job.progress_percent === "number") return Math.max(0, Math.min(100, job.progress_percent));
  if (job.status === "completed") return 100;
  return null;
}

export function ImageConsole({ initialSnapshot }: { initialSnapshot: ImageSnapshot }) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [state, setState] = useState<RunState>("idle");
  const [message, setMessage] = useState("");
  const initialProfile = initialSnapshot.profiles.find((profile) => profile.recommended) ?? initialSnapshot.profiles[0];
  const [selectedProfile, setSelectedProfile] = useState(initialProfile?.id ?? "flux2-klein-4b");
  const [settings, setSettings] = useState(() => {
    const profile = initialProfile;
    return {
      width: profile?.default_width ?? 1024,
      height: profile?.default_height ?? 1024,
      steps: profile?.default_steps ?? 4,
      guidance_scale: profile?.guidance_scale ?? 0,
      seed: -1,
    };
  });
  const selectedProfileInfo = useMemo(() => snapshot.profiles.find((profile) => profile.id === selectedProfile), [selectedProfile, snapshot.profiles]);
  const resolutionOptions = selectedProfileInfo?.resolution_options?.length
    ? selectedProfileInfo.resolution_options
    : [{ label: `${settings.width} x ${settings.height}`, width: settings.width, height: settings.height }];
  const selectedResolution = `${settings.width}x${settings.height}`;
  const activeJob = useMemo(() => snapshot.jobs.find((job) => job.status === "running" || job.status === "queued"), [snapshot.jobs]);

  async function refresh(): Promise<void> {
    const response = await fetch("/api/images", { cache: "no-store" });
    setSnapshot(await response.json() as ImageSnapshot);
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
      setMessage(error instanceof Error ? error.message : "Image action failed");
    }
  }

  useEffect(() => {
    return subscribeApplianceEvent<ImageSnapshot>("images", setSnapshot);
  }, []);

  async function downloadModel(profile: string): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/images", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "downloadModel", profile }),
      });
      await parseJson(response);
      setMessage("Model download started or verified.");
    }, "Checking/downloading image model.");
  }

  async function createJob(formData: FormData): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/images", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "createJob",
          profile: formData.get("profile"),
          prompt: formData.get("prompt"),
          negative_prompt: formData.get("negative_prompt"),
          width: Number(formData.get("width")),
          height: Number(formData.get("height")),
          steps: Number(formData.get("steps")),
          guidance_scale: Number(formData.get("guidance_scale")),
          seed: Number(formData.get("seed") || -1),
        }),
      });
      await parseJson(response);
      setMessage("Image job queued. The LLM is stopped while the GPU renders.");
    }, "Queueing image generation.");
  }

  async function deleteJob(id: string): Promise<void> {
    await run(async () => {
      const response = await fetch("/api/images", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "deleteJob", id }),
      });
      await parseJson(response);
      setMessage("Image job deleted.");
    }, "Deleting image job.");
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(420px,0.8fr)_minmax(0,1.2fr)]">
      <section className="xl:col-span-2">
        <div className="flex flex-wrap items-center justify-between gap-3 border border-white/10 bg-[#07121a] px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center border border-violet-400/40 bg-violet-400/10 text-violet-200">
              <ImageIcon className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-white">Image Generation</h1>
              <p className="text-sm text-slate-400">{snapshot.serviceUrl}</p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
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
          <div className={cn("mt-3 border px-4 py-3 text-sm", state === "error" ? "border-red-400/30 bg-red-500/10 text-red-200" : "border-violet-400/30 bg-violet-500/10 text-violet-100")}>
            {state === "working" ? "Working: " : null}{message}
          </div>
        ) : null}
        {!snapshot.healthy && snapshot.error ? <div className="mt-3 border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">{snapshot.error}</div> : null}
      </section>

      <SectionCard title="Generate" description="Select a tested image model. Rendering temporarily unloads the LLM to free VRAM.">
        <form action={(formData) => void createJob(formData)} className="grid gap-3">
          <label className="grid gap-1 text-xs text-slate-400">
            Model
            <select
              name="profile"
              value={selectedProfile}
              onChange={(event) => {
                const nextProfile = snapshot.profiles.find((profile) => profile.id === event.target.value);
                setSelectedProfile(event.target.value);
                if (nextProfile) {
                  setSettings((current) => ({
                    ...current,
                    width: nextProfile.default_width,
                    height: nextProfile.default_height,
                  steps: nextProfile.default_steps,
                    guidance_scale: nextProfile.guidance_scale,
                  }));
                }
              }}
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
          <label className="grid gap-1 text-xs text-slate-400">
            Prompt
            <textarea name="prompt" required rows={6} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-violet-400/60" placeholder="A realistic photo of a compact AI appliance on a workbench, tiny status LEDs, shallow depth of field, crisp details." />
          </label>
          <label className="grid gap-1 text-xs text-slate-400">
            Negative prompt
            <textarea
              name="negative_prompt"
              rows={3}
              disabled={selectedProfileInfo?.supports_negative_prompt === false}
              className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-violet-400/60 disabled:cursor-not-allowed disabled:opacity-50"
              placeholder={selectedProfileInfo?.supports_negative_prompt === false ? "This model does not use negative prompts." : "blurry, low quality, watermark, text, distorted"}
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-4">
            <label className="grid gap-1 text-xs text-slate-400">
              Size
              <select
                value={selectedResolution}
                onChange={(event) => {
                  const [width, height] = event.target.value.split("x").map(Number);
                  setSettings((current) => ({ ...current, width, height }));
                }}
                className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none"
              >
                {resolutionOptions.map((option) => (
                  <option key={`${option.width}x${option.height}`} value={`${option.width}x${option.height}`}>{option.label}</option>
                ))}
              </select>
              <input type="hidden" name="width" value={settings.width} />
              <input type="hidden" name="height" value={settings.height} />
            </label>
            <label className="grid gap-1 text-xs text-slate-400">
              Steps
              {selectedProfileInfo?.step_options?.length ? (
                <select name="steps" value={settings.steps} onChange={(event) => setSettings((current) => ({ ...current, steps: Number(event.target.value) }))} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none">
                  {selectedProfileInfo.step_options.map((steps) => <option key={steps} value={steps}>{steps}</option>)}
                </select>
              ) : (
                <input name="steps" type="number" min={1} max={50} value={settings.steps} onChange={(event) => setSettings((current) => ({ ...current, steps: Number(event.target.value) }))} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none" />
              )}
            </label>
            <label className="grid gap-1 text-xs text-slate-400">
              Guidance
              {selectedProfileInfo?.guidance_options?.length ? (
                <select name="guidance_scale" value={settings.guidance_scale} onChange={(event) => setSettings((current) => ({ ...current, guidance_scale: Number(event.target.value) }))} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none">
                  {selectedProfileInfo.guidance_options.map((guidance) => <option key={guidance} value={guidance}>{guidance}</option>)}
                </select>
              ) : (
                <input name="guidance_scale" type="number" min={0} max={12} step={0.1} value={settings.guidance_scale} onChange={(event) => setSettings((current) => ({ ...current, guidance_scale: Number(event.target.value) }))} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none" />
              )}
            </label>
            <label className="grid gap-1 text-xs text-slate-400">
              Seed
              <input name="seed" type="number" value={settings.seed} onChange={(event) => setSettings((current) => ({ ...current, seed: Number(event.target.value) }))} className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none" />
            </label>
          </div>
          <button disabled={state === "working" || Boolean(activeJob) || !selectedProfileInfo?.ready} className="inline-flex items-center justify-center gap-2 border border-violet-400/40 bg-violet-400/10 px-4 py-2 text-sm font-medium text-violet-100 hover:bg-violet-400/20 disabled:opacity-50">
            <Wand2 className="h-4 w-4" />
            Queue Image
          </button>
        </form>
      </SectionCard>

      <SectionCard title="Model Profiles" description="Profiles are marked installed when the required model snapshot exists locally.">
        <div className="grid gap-3">
          {snapshot.profiles.map((profile: ImageProfile) => (
            <div key={profile.id} className="grid gap-3 border border-white/10 bg-black/20 p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2 font-medium text-white">{profile.name}{profile.recommended ? <span className="border border-cyan-400/40 bg-cyan-400/10 px-2 py-0.5 text-[10px] uppercase text-cyan-100">Recommended</span> : null}</div>
                  <div className="mt-1 text-xs text-slate-500">{profile.repo}</div>
                </div>
                <span className={cn("border px-2 py-1 text-xs", profile.ready ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-200" : "border-amber-400/40 bg-amber-400/10 text-amber-200")}>
                  {profile.ready ? "installed" : "missing"}
                </span>
              </div>
              <p className="text-sm text-slate-300">{profile.description}</p>
              {profile.resolution_options?.length ? (
                <p className="text-xs text-cyan-200">Tested sizes: {profile.resolution_options.map((option) => `${option.width}x${option.height}`).join(", ")}</p>
              ) : null}
              {profile.test_summary ? <p className="text-xs text-slate-500">{profile.test_summary}</p> : null}
              {profile.error ? <p className="text-xs text-red-200">{profile.error}</p> : null}
              <button disabled={state === "working" || profile.ready} className="inline-flex items-center justify-center gap-2 border border-cyan-400/40 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-400/20 disabled:opacity-50" onClick={() => void downloadModel(profile.id)}>
                <Download className="h-4 w-4" />
                {profile.ready ? "Model Installed" : "Download Model"}
              </button>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Jobs" className="xl:col-span-2">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {snapshot.jobs.length === 0 ? <p className="text-sm text-slate-400">No image jobs yet.</p> : null}
          {snapshot.jobs.map((job: ImageJob) => (
            <article key={job.id} className="overflow-hidden border border-white/10 bg-black/20">
              <div className="aspect-square border-b border-white/10 bg-black/30">
                {job.status === "completed" ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img className="h-full w-full object-contain" src={imageOutputUrl(job.id)} alt={job.prompt} />
                ) : (
                  <div className="flex h-full items-center justify-center p-4 text-center text-sm text-slate-500">{job.status}</div>
                )}
              </div>
              <div className="grid gap-2 p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className={cn("border px-2 py-0.5 text-xs", job.status === "completed" ? "border-emerald-400/40 text-emerald-200" : job.status === "failed" ? "border-red-400/40 text-red-200" : "border-violet-400/40 text-violet-200")}>{job.status}</span>
                  <button disabled={state === "working" || job.status === "running"} className="inline-flex h-8 w-8 items-center justify-center border border-red-400/30 bg-red-500/10 text-red-200 hover:bg-red-500/20 disabled:opacity-40" onClick={() => void deleteJob(job.id)}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                <p className="line-clamp-2 min-h-10 text-sm text-slate-200">{job.prompt}</p>
                {progressValue(job) !== null ? (
                  <div className="grid gap-1">
                    <div className="flex items-center justify-between gap-3 text-[11px] text-slate-400">
                      <span className="truncate">{job.progress_label ?? "Progress"}</span>
                      <span className="font-mono text-slate-300">{progressValue(job)?.toFixed(progressValue(job)! % 1 === 0 ? 0 : 1)}%</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
                      <div className="h-full rounded-full bg-violet-300" style={{ width: `${progressValue(job)}%` }} />
                    </div>
                    {(job.status === "running" || job.status === "queued") ? (
                      <div className="flex items-center justify-between gap-2 text-[11px] text-slate-500">
                        <span>{job.progress_step && job.progress_total ? `${job.progress_step}/${job.progress_total} steps` : job.status}</span>
                        <span>{formatEta(job.eta_seconds)}</span>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                <div className="grid grid-cols-3 gap-2 text-center text-[11px] text-slate-400">
                  <div className="border border-white/10 bg-white/[0.03] px-1 py-1">{job.width}x{job.height}</div>
                  <div className="border border-white/10 bg-white/[0.03] px-1 py-1">{job.steps} steps</div>
                  <div className="border border-white/10 bg-white/[0.03] px-1 py-1">{metric(job.duration_seconds, "s")}</div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-center text-[11px] text-slate-400">
                  <div className="border border-white/10 bg-white/[0.03] px-1 py-1">VRAM {metric(job.peak_vram_mb, " MB")}</div>
                  <div className="border border-white/10 bg-white/[0.03] px-1 py-1">Jct {metric(job.peak_junction_c, " C")}</div>
                </div>
                {job.error ? <div className="line-clamp-3 border border-red-400/30 bg-red-500/10 px-2 py-1 text-xs text-red-100">{job.error}</div> : null}
              </div>
            </article>
          ))}
        </div>
      </SectionCard>
    </div>
  );
}
