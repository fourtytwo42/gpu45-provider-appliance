"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AudioLines, Check, Download, FileAudio, Guitar, Loader2, Music2,
  RefreshCw, RotateCcw, Sparkles, Square, Trash2, Upload, WandSparkles,
} from "lucide-react";
import { subscribeApplianceEvent } from "@/lib/appliance-events";
import { cn } from "@/lib/cn";
import { musicOutputUrl, type MusicJob, type MusicMode, type MusicProfile, type MusicSnapshot, type MusicTaskType } from "@/lib/music";
import { SectionCard } from "./section-card";
import { StatusBadge } from "./status-badge";

const MODES: Array<{ id: MusicMode; label: string; icon: typeof Music2 }> = [
  { id: "create", label: "Create", icon: Sparkles },
  { id: "reference", label: "Reference", icon: FileAudio },
  { id: "edit", label: "Edit", icon: WandSparkles },
  { id: "stems", label: "Stems", icon: AudioLines },
];

const TASK_LABELS: Record<MusicTaskType, string> = {
  text2music: "Generate song", cover: "Cover / style transfer", repaint: "Repaint range",
  complete: "Complete arrangement", lego: "Add a layer", extract: "Extract a track",
  reference: "Reference generation", separate: "Vocals + instrumental",
};

function tasksFor(profile: MusicProfile | undefined, mode: MusicMode): MusicTaskType[] {
  if (!profile) return [];
  const desired: Record<MusicMode, MusicTaskType[]> = {
    create: ["text2music"],
    reference: profile.backend === "levo" ? ["reference"] : ["cover"],
    edit: ["cover", "repaint", "complete", "lego"],
    stems: profile.backend === "levo" ? ["separate"] : ["extract"],
  };
  return desired[mode].filter((task) => profile.taskTypes.includes(task));
}

function terminal(status: MusicJob["status"]): boolean { return ["completed", "failed", "cancelled"].includes(status); }
function active(status: MusicJob["status"]): boolean { return ["preparing", "queued", "waiting", "running", "restoring"].includes(status); }
function statusTone(status: MusicJob["status"]): "neutral" | "info" | "success" | "warning" | "danger" | "creative" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "cancelled") return "neutral";
  if (status === "running") return "creative";
  return "warning";
}
function formatEta(seconds?: number | null): string {
  if (seconds == null || seconds < 0) return "Learning ETA";
  if (seconds < 60) return `${Math.ceil(seconds)}s left`;
  const minutes = Math.floor(seconds / 60); const remainder = Math.ceil(seconds % 60);
  return `${minutes}m ${remainder}s left`;
}
function humanStage(stage: string): string { return stage.replaceAll("-", " ").replace(/\b\w/g, (value) => value.toUpperCase()); }

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let payload: Record<string, unknown> = {};
  try { payload = JSON.parse(text) as Record<string, unknown>; } catch { throw new Error(`Music request failed (${response.status}).`); }
  if (!response.ok) throw new Error(String(payload.error ?? "Music request failed."));
  return payload as T;
}

function Waveform({ url }: { url: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) return;
        const context = new AudioContext();
        const decoded = await context.decodeAudioData(await response.arrayBuffer());
        if (cancelled || !canvas.current) { void context.close(); return; }
        const values = decoded.getChannelData(0); const bars = 120; const stride = Math.max(1, Math.floor(values.length / bars));
        const peaks = Array.from({ length: bars }, (_, index) => {
          let peak = 0; const start = index * stride; const end = Math.min(values.length, start + stride);
          for (let cursor = start; cursor < end; cursor += Math.max(1, Math.floor(stride / 64))) peak = Math.max(peak, Math.abs(values[cursor]));
          return peak;
        });
        const element = canvas.current; const scale = window.devicePixelRatio || 1; const width = element.clientWidth; const height = element.clientHeight;
        element.width = width * scale; element.height = height * scale;
        const drawing = element.getContext("2d"); if (!drawing) return;
        drawing.scale(scale, scale); drawing.clearRect(0, 0, width, height); drawing.fillStyle = "#a78bfa";
        const barWidth = width / bars;
        peaks.forEach((peak, index) => { const value = Math.max(2, peak * (height - 4)); drawing.fillRect(index * barWidth, (height - value) / 2, Math.max(1, barWidth - 1), value); });
        void context.close();
      } catch { /* The audio player remains available when waveform decoding is unsupported. */ }
    })();
    return () => { cancelled = true; };
  }, [url]);
  return <canvas ref={canvas} aria-hidden="true" className="h-14 w-full rounded-md bg-[#0a1018]" />;
}

function JobRow({ job, onAction }: { job: MusicJob; onAction: (id: string, action: "cancel" | "retry" | "delete") => void }) {
  const masterUrl = musicOutputUrl(job.id);
  const assetNames = Object.keys(job.assets ?? {}).filter((asset) => ["master", "preview", "vocals", "instrumental"].includes(asset));
  return <article className="rounded-lg border border-[#223044] bg-[#101822] p-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="truncate text-sm font-semibold text-white">{job.profile_name ?? job.profile_id}</h3><StatusBadge tone={statusTone(job.status)}>{job.status}</StatusBadge>{job.noncommercial ? <StatusBadge tone="warning">Noncommercial</StatusBadge> : null}</div><p className="mt-1 line-clamp-2 text-xs text-[#8a98aa]">{String(job.payload.caption ?? TASK_LABELS[job.task_type])}</p></div><div className="flex items-center gap-1">{active(job.status) ? <button type="button" title="Cancel" aria-label="Cancel music job" onClick={() => onAction(job.id, "cancel")} className="icon-button"><Square className="h-4 w-4" /></button> : null}{job.status === "failed" || job.status === "cancelled" ? <button type="button" title="Retry" aria-label="Retry music job" onClick={() => onAction(job.id, "retry")} className="icon-button"><RotateCcw className="h-4 w-4" /></button> : null}{terminal(job.status) ? <button type="button" title="Delete" aria-label="Delete music job" onClick={() => onAction(job.id, "delete")} className="icon-button text-[#fb4b6b]"><Trash2 className="h-4 w-4" /></button> : null}</div></div>
    {active(job.status) ? <div className="mt-4"><div className="mb-2 flex justify-between text-xs"><span className="text-[#cdd7e3]">{humanStage(job.stage)}</span><span className="font-mono text-[#8a98aa]">{Math.round(job.progress)}% - {formatEta(job.eta_seconds)}</span></div><div className="h-2 overflow-hidden rounded-full bg-[#070a0f]"><div className="h-full rounded-full bg-[#a78bfa] transition-[width] duration-500" style={{ width: `${Math.max(2, Math.min(100, job.progress))}%` }} /></div></div> : null}
    {job.status === "failed" && job.error ? <div className="mt-3 rounded-md border border-[#fb4b6b]/30 bg-[#fb4b6b]/10 px-3 py-2 text-xs text-[#fecdd3]">{job.error}</div> : null}
    {job.status === "completed" ? <div className="mt-4 space-y-3"><Waveform url={masterUrl} /><audio controls preload="metadata" className="h-10 w-full" src={masterUrl} /><div className="flex flex-wrap gap-2">{assetNames.map((asset) => <a key={asset} href={musicOutputUrl(job.id, asset)} download className="inline-flex h-9 items-center gap-2 rounded-md border border-[#31415a] px-3 text-xs text-[#cdd7e3] hover:border-[#a78bfa] hover:text-white"><Download className="h-3.5 w-3.5" />{asset === "master" ? "Master" : asset}</a>)}</div>{Object.keys(job.metrics ?? {}).length ? <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-[#718096]"><span>{Number(job.metrics.durationSeconds ?? 0).toFixed(1)}s audio</span><span>{Number(job.metrics.realTimeFactor ?? 0).toFixed(2)}x realtime</span><span>{String(job.metrics.backend ?? job.profile_id)}</span></div> : null}</div> : null}
  </article>;
}

export function MusicConsole({ initialSnapshot }: { initialSnapshot: MusicSnapshot }) {
  const [snapshot, setSnapshot] = useState(initialSnapshot);
  const [mode, setMode] = useState<MusicMode>("create");
  const firstProfile = initialSnapshot.profiles.find((profile) => profile.ready && profile.recommended) ?? initialSnapshot.profiles.find((profile) => profile.ready);
  const [profileId, setProfileId] = useState(firstProfile?.id ?? "ace-xl-turbo-4b");
  const [taskType, setTaskType] = useState<MusicTaskType>("text2music");
  const [duration, setDuration] = useState(firstProfile?.duration.default ?? 60);
  const [instrumental, setInstrumental] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [visibleJobs, setVisibleJobs] = useState(12);
  const profile = useMemo(() => snapshot.profiles.find((item) => item.id === profileId), [profileId, snapshot.profiles]);
  const availableTasks = useMemo(() => tasksFor(profile, mode), [mode, profile]);
  const compatibleProfiles = useMemo(() => snapshot.profiles.filter((item) => item.modes.includes(mode)), [mode, snapshot.profiles]);

  useEffect(() => subscribeApplianceEvent<MusicSnapshot>("music", setSnapshot), []);

  function chooseMode(nextMode: MusicMode): void {
    setMode(nextMode);
    const replacement = snapshot.profiles.find((item) => item.ready && item.recommended && item.modes.includes(nextMode))
      ?? snapshot.profiles.find((item) => item.ready && item.modes.includes(nextMode))
      ?? snapshot.profiles.find((item) => item.modes.includes(nextMode));
    const nextProfile = profile?.modes.includes(nextMode) ? profile : replacement;
    if (!nextProfile) return;
    setProfileId(nextProfile.id);
    setDuration(nextProfile.duration.default);
    setTaskType(tasksFor(nextProfile, nextMode)[0] ?? "text2music");
  }

  function chooseProfile(nextId: string): void {
    const nextProfile = snapshot.profiles.find((item) => item.id === nextId);
    setProfileId(nextId);
    if (!nextProfile) return;
    setDuration(nextProfile.duration.default);
    const nextTasks = tasksFor(nextProfile, mode);
    if (!nextTasks.includes(taskType)) setTaskType(nextTasks[0] ?? "text2music");
  }

  async function refresh(): Promise<void> {
    const response = await fetch("/api/music", { cache: "no-store" });
    setSnapshot(await parseResponse<MusicSnapshot>(response));
  }
  async function jobAction(id: string, action: "cancel" | "retry" | "delete"): Promise<void> {
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`/api/music/jobs/${encodeURIComponent(id)}${action === "delete" ? "" : "/action"}`, {
        method: action === "delete" ? "DELETE" : "POST",
        headers: action === "delete" ? undefined : { "Content-Type": "application/json" },
        body: action === "delete" ? undefined : JSON.stringify({ action }),
      });
      await parseResponse(response); await refresh(); setMessage(action === "delete" ? "Music job and its files were deleted." : `${action === "cancel" ? "Cancellation" : "Retry"} requested.`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Music action failed."); } finally { setBusy(false); }
  }
  async function acceptLicense(): Promise<void> {
    setBusy(true);
    try {
      const response = await fetch("/api/music/licenses/levo2/accept", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ licenseHash: snapshot.license.levo2.hash }) });
      await parseResponse(response); await refresh(); setMessage("LeVo 2 noncommercial license accepted for this appliance account.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "License acceptance failed."); } finally { setBusy(false); }
  }
  async function submit(event: React.FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const form = new FormData(event.currentTarget);
      form.set("profile_id", profileId); form.set("mode", mode); form.set("task_type", taskType); form.set("duration", String(duration));
      if (instrumental) form.set("instrumental", "true"); else form.delete("instrumental");
      const source = form.get("audio_upload"); form.delete("audio_upload");
      if (source instanceof File && source.size > 0) form.set(mode === "reference" && profile?.backend === "levo" ? "reference_audio" : "source_audio", source);
      const response = await fetch("/api/music/jobs", { method: "POST", body: form });
      await parseResponse<MusicJob>(response); await refresh(); setMessage("Music job queued. GPU ownership and model restoration are handled automatically.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Music job could not be queued."); } finally { setBusy(false); }
  }

  const levoSelected = profile?.backend === "levo";
  const needsAudio = mode !== "create";
  const showsRange = taskType === "repaint" || taskType === "lego";
  const showsTrack = taskType === "extract" || taskType === "lego";
  const jobs = snapshot.jobs.slice(0, visibleJobs);

  return <div className="space-y-5">
    {!snapshot.healthy ? <div className="rounded-lg border border-[#fb4b6b]/35 bg-[#fb4b6b]/10 p-4 text-sm text-[#fecdd3]">{snapshot.error ?? "Music service is offline."}</div> : null}
    <div className="grid gap-5 2xl:grid-cols-[minmax(0,0.9fr)_minmax(30rem,1.1fr)]">
      <SectionCard title="Compose" description="The selected model determines which workflows and controls are available.">
        <form onSubmit={(event) => void submit(event)} className="space-y-5">
          <div className="grid grid-cols-4 gap-1 rounded-lg bg-[#0a1018] p-1">{MODES.map(({ id, label, icon: Icon }) => <button key={id} type="button" onClick={() => chooseMode(id)} className={cn("flex min-h-10 items-center justify-center gap-2 rounded-md px-2 text-xs transition", mode === id ? "bg-[#20283a] text-[#e9d5ff]" : "text-[#718096] hover:text-white")}><Icon className="h-3.5 w-3.5" /><span className="hidden sm:inline">{label}</span></button>)}</div>
          <label className="block text-xs font-medium text-[#8a98aa]">Model<select value={profileId} onChange={(event) => chooseProfile(event.target.value)} className="input-control mt-2 w-full">{compatibleProfiles.map((item) => <option key={item.id} value={item.id} disabled={!item.ready}>{item.name}{item.ready ? "" : " - unavailable"}</option>)}</select></label>
          {profile ? <div className="flex flex-wrap items-center gap-2 rounded-md bg-[#0a1018] px-3 py-2 text-xs text-[#8a98aa]"><StatusBadge tone={profile.ready ? "success" : "danger"}>{profile.ready ? "Ready" : "Unavailable"}</StatusBadge>{profile.recommended ? <StatusBadge tone="info">Recommended</StatusBadge> : null}{profile.experimental ? <StatusBadge tone="warning">Experimental</StatusBadge> : null}<span>{profile.expectedVramGb} GB expected VRAM</span><span>{profile.description}</span></div> : null}
          {availableTasks.length > 1 ? <label className="block text-xs font-medium text-[#8a98aa]">Operation<select value={taskType} onChange={(event) => setTaskType(event.target.value as MusicTaskType)} className="input-control mt-2 w-full">{availableTasks.map((task) => <option key={task} value={task}>{TASK_LABELS[task]}</option>)}</select></label> : null}
          {levoSelected && !snapshot.license.levo2.accepted ? <div className="rounded-lg border border-[#fbbf24]/35 bg-[#fbbf24]/10 p-3 text-sm text-[#fde68a]"><div className="font-semibold">LeVo 2 is noncommercial</div><p className="mt-1 text-xs opacity-80">{snapshot.license.levo2.text}</p><button type="button" disabled={busy} onClick={() => void acceptLicense()} className="mt-3 inline-flex h-9 items-center gap-2 rounded-md bg-[#fbbf24] px-3 text-xs font-semibold text-[#171006]"><Check className="h-3.5 w-3.5" />Accept current license</button></div> : null}
          <label className="block text-xs font-medium text-[#8a98aa]">Prompt<textarea name="caption" rows={3} placeholder="Genre, instruments, mood, vocal style, production, and song arc" className="input-control mt-2 w-full resize-y" /></label>
          {mode === "create" || mode === "reference" || taskType === "complete" ? <label className="block text-xs font-medium text-[#8a98aa]">Lyrics<textarea name="lyrics" rows={8} placeholder={instrumental ? "Instrumental mode is enabled" : "[Verse]\nWrite structured lyrics here...\n\n[Chorus]\n..."} disabled={instrumental} className="input-control mt-2 w-full resize-y disabled:opacity-50" /></label> : null}
          <div className="grid gap-4 sm:grid-cols-2"><label className="text-xs font-medium text-[#8a98aa]">Duration <span className="font-mono text-white">{duration}s</span><input type="range" min={profile?.duration.min ?? 10} max={profile?.duration.max ?? 600} step={5} value={duration} onChange={(event) => setDuration(Number(event.target.value))} className="mt-3 w-full accent-[#a78bfa]" /></label><label className="text-xs font-medium text-[#8a98aa]">BPM<input name="bpm" type="number" min="40" max="240" placeholder="Auto" className="input-control mt-2 w-full" /></label></div>
          <div className="grid gap-3 sm:grid-cols-3"><label className="text-xs font-medium text-[#8a98aa]">Key<input name="key" placeholder="Auto" className="input-control mt-2 w-full" /></label><label className="text-xs font-medium text-[#8a98aa]">Time signature<select name="time_signature" defaultValue="" className="input-control mt-2 w-full"><option value="">Auto</option><option>4/4</option><option>3/4</option><option>6/8</option></select></label><label className="text-xs font-medium text-[#8a98aa]">Language<select name="language" defaultValue="en" className="input-control mt-2 w-full"><option value="en">English</option><option value="es">Spanish</option><option value="zh">Chinese</option><option value="unknown">Auto</option></select></label></div>
          {needsAudio ? <label className="flex min-h-28 cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-[#31415a] bg-[#0a1018] px-4 text-center hover:border-[#a78bfa]"><Upload className="h-5 w-5 text-[#a78bfa]" /><span className="mt-2 text-sm text-white">{mode === "reference" ? "Reference audio" : "Source audio"}</span><span className="mt-1 text-xs text-[#718096]">Audio or video with an audio track, up to 512 MB</span><input required type="file" name="audio_upload" accept="audio/*,video/*" className="sr-only" /></label> : null}
          {showsRange ? <div className="grid grid-cols-2 gap-3"><label className="text-xs font-medium text-[#8a98aa]">Start second<input name="repainting_start" type="number" min="0" step="0.1" defaultValue="0" className="input-control mt-2 w-full" /></label><label className="text-xs font-medium text-[#8a98aa]">End second<input name="repainting_end" type="number" min="0" step="0.1" defaultValue={duration} className="input-control mt-2 w-full" /></label></div> : null}
          {showsTrack ? <label className="block text-xs font-medium text-[#8a98aa]">Track<select name="track_name" defaultValue={taskType === "extract" ? "vocals" : "guitar"} className="input-control mt-2 w-full"><option value="vocals">Vocals</option><option value="instrumental">Instrumental</option><option value="guitar">Guitar</option><option value="drums">Drums</option><option value="bass">Bass</option><option value="piano">Piano</option></select></label> : null}
          {taskType === "complete" ? <label className="block text-xs font-medium text-[#8a98aa]">Tracks to add<input name="track_classes" defaultValue="drums, bass, guitar" className="input-control mt-2 w-full" /></label> : null}
          {mode === "reference" ? <label className="block text-xs font-medium text-[#8a98aa]">Reference strength<input name="reference_strength" type="range" min="0.1" max="1.5" step="0.05" defaultValue="1" className="mt-3 w-full accent-[#a78bfa]" /></label> : null}
          <details className="rounded-lg border border-[#223044] bg-[#0a1018]"><summary className="cursor-pointer px-3 py-3 text-xs font-medium text-[#8a98aa]">Advanced generation settings</summary><div className="grid gap-3 border-t border-[#223044] p-3 sm:grid-cols-3"><label className="text-xs text-[#8a98aa]">Seed<input name="seed" type="number" defaultValue="-1" className="input-control mt-2 w-full" /></label>{profile?.stepOptions.length ? <label className="text-xs text-[#8a98aa]">Steps<select name="steps" defaultValue={profile.defaultSteps ?? profile.stepOptions[0]} className="input-control mt-2 w-full">{profile.stepOptions.map((value) => <option key={value}>{value}</option>)}</select></label> : null}<label className="text-xs text-[#8a98aa]">Format<select name="output_format" className="input-control mt-2 w-full">{(profile?.outputFormats ?? ["wav"]).map((value) => <option key={value}>{value.toUpperCase()}</option>)}</select></label></div></details>
          <label className="flex items-center gap-3 text-sm text-[#cdd7e3]"><input type="checkbox" checked={instrumental} onChange={(event) => setInstrumental(event.target.checked)} className="h-4 w-4 accent-[#a78bfa]" />Instrumental, no vocals</label>
          <button disabled={busy || !profile?.ready || availableTasks.length === 0 || (levoSelected && !snapshot.license.levo2.accepted)} className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-[#a78bfa] text-sm font-semibold text-[#10091b] hover:bg-[#c4b5fd] disabled:cursor-not-allowed disabled:opacity-45">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Guitar className="h-4 w-4" />}{busy ? "Working" : TASK_LABELS[taskType]}</button>
          {message ? <div aria-live="polite" className="rounded-md bg-[#0a1018] px-3 py-2 text-xs text-[#cdd7e3]">{message}</div> : null}
        </form>
      </SectionCard>
      <SectionCard title="Jobs and outputs" description="Progress survives refreshes and completed audio stays available here." actions={<button type="button" onClick={() => void refresh()} title="Refresh music jobs" aria-label="Refresh music jobs" className="icon-button"><RefreshCw className="h-4 w-4" /></button>}>
        <div className="space-y-3">{jobs.map((job) => <JobRow key={job.id} job={job} onAction={(id, action) => void jobAction(id, action)} />)}{jobs.length === 0 ? <div className="rounded-lg border border-dashed border-[#223044] py-16 text-center"><Music2 className="mx-auto h-7 w-7 text-[#617083]" /><div className="mt-3 text-sm text-white">No music jobs yet</div><p className="mt-1 text-xs text-[#718096]">Your generated tracks and editing runs will appear here.</p></div> : null}{snapshot.jobs.length > visibleJobs ? <button type="button" onClick={() => setVisibleJobs((value) => value + 12)} className="h-10 w-full rounded-md border border-[#31415a] text-sm text-[#cdd7e3] hover:border-[#a78bfa]">Load more</button> : null}</div>
      </SectionCard>
    </div>
  </div>;
}
