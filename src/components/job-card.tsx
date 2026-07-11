"use client";

import { Download, ExternalLink, FileAudio, FileText, Film, ImageIcon, LoaderCircle, Mic2, PackageCheck, RotateCcw, Square, TerminalSquare, Trash2, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import type { UnifiedJob, UnifiedJobAction } from "@/lib/jobs";
import { StatusBadge } from "./status-badge";

const iconMap = { download: Download, benchmark: TerminalSquare, tts: Mic2, "pocket-tts": Mic2, audiobook: FileAudio, whisper: FileText, image: ImageIcon, video: Film, "model-training": PackageCheck, voice: Mic2, presentation: FileAudio };
const toneMap = { queued: "info", running: "success", paused: "warning", unknown: "neutral", completed: "success", failed: "danger", cancelled: "warning", stopped: "warning", needs_review: "warning" } as const;
const actionIcons = { cancel: Square, delete: Trash2, retry: RotateCcw, download: ExternalLink };

function dateLabel(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

async function runAction(id: string, action: UnifiedJobAction): Promise<string> {
  const response = await fetch("/api/jobs/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, action }),
  });
  const payload = await response.json() as { ok?: boolean; message?: string };
  if (!response.ok || !payload.ok) throw new Error(payload.message ?? "Job action failed.");
  return payload.message ?? "Done.";
}

export function JobCard({ job, compact = false }: { job: UnifiedJob; compact?: boolean }) {
  const Icon = iconMap[job.kind] ?? LoaderCircle;
  const progress = typeof job.progressPercent === "number" ? Math.max(0, Math.min(100, job.progressPercent)) : null;
  const [workingAction, setWorkingAction] = useState<UnifiedJobAction | null>(null);
  const [message, setMessage] = useState("");

  async function handleAction(action: UnifiedJobAction) {
    if (action === "download" && job.outputUrl) {
      window.open(job.outputUrl, "_blank", "noopener,noreferrer");
      return;
    }
    if (action === "delete" && !window.confirm(`Delete ${job.title}?`)) return;
    if (action === "cancel" && !window.confirm(`Cancel ${job.title}?`)) return;
    setWorkingAction(action);
    setMessage("");
    try {
      const nextMessage = await runAction(job.id, action);
      setMessage(nextMessage);
      window.setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Job action failed.");
    } finally {
      setWorkingAction(null);
    }
  }

  return (
    <article className={cn("rounded-lg border border-[#223044] bg-[#0d131c] p-4", compact && "p-3")}>
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-[#223044] bg-[#121a26] text-[#21d4fd]"><Icon className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge tone={toneMap[job.status]}>{job.displayStatus ?? job.status.replace("_", " ")}</StatusBadge><span className="text-xs text-[#617083]">{job.kind.replace("-", " ")}</span></div>
          <h3 className="mt-2 truncate text-sm font-semibold text-[#e6edf5]" title={job.title}>{job.title}</h3>
          {job.subtitle ? <p className="mt-1 line-clamp-2 text-sm text-[#8a98aa]" title={job.subtitle}>{job.subtitle}</p> : null}
          {progress !== null ? <div className="mt-3"><div className="mb-1 flex justify-between gap-3 text-xs text-[#8a98aa]"><span>{job.progressLabel ?? "Progress"}</span><span className="font-mono">{progress.toFixed(progress % 1 === 0 ? 0 : 1)}%</span></div><div className="h-1.5 overflow-hidden rounded-full bg-[#223044]"><div className="h-full rounded-full bg-[#21d4fd]" style={{ width: `${progress}%` }} /></div></div> : null}
          {job.error ? <details className="mt-3 rounded-md bg-[#24151a] px-3 py-2 text-sm text-rose-100"><summary className="flex cursor-pointer list-none gap-2"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" /><span className="line-clamp-2">{job.userMessage ?? "This job needs attention."}</span></summary><pre className="mt-3 max-h-52 overflow-auto whitespace-pre-wrap border-t border-[#fb4b6b]/20 pt-3 font-mono text-xs text-[#c99aa5]">{job.technicalError ?? job.error}</pre></details> : null}
          {message ? <div className="mt-3 rounded-md border border-[#223044] bg-[#121a26] px-3 py-2 text-xs text-[#cbd5e1]">{message}</div> : null}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-[#617083]">
            <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">{job.model ? <span className="truncate">Model: {job.model}</span> : null}<span>{dateLabel(job.updatedAt ?? job.finishedAt ?? job.createdAt)}</span>{job.outputUrl ? <a href={job.outputUrl} className="inline-flex items-center gap-1 text-[#21d4fd] hover:text-cyan-100"><ExternalLink className="h-3.5 w-3.5" />Output</a> : null}</div>
            {job.actions?.length ? <div className="flex shrink-0 flex-wrap items-center gap-1.5">{job.actions.map((action) => { const ActionIcon = actionIcons[action]; return <button key={action} disabled={workingAction !== null} onClick={() => void handleAction(action)} className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs transition disabled:opacity-40", action === "delete" ? "border-[#fb4b6b]/30 bg-[#fb4b6b]/10 text-rose-100 hover:bg-[#fb4b6b]/20" : "border-[#223044] bg-[#121a26] text-[#cbd5e1] hover:border-[#21d4fd]/40 hover:text-cyan-100")}><ActionIcon className={cn("h-3.5 w-3.5", workingAction === action && "animate-pulse")} />{job.actionLabels?.[action] ?? action}</button>; })}</div> : null}
          </div>
        </div>
      </div>
    </article>
  );
}
