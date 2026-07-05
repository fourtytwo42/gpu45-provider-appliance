import { Download, ExternalLink, FileAudio, FileText, Film, ImageIcon, LoaderCircle, Mic2, PackageCheck, TerminalSquare, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import type { UnifiedJob } from "@/lib/jobs";
import { StatusBadge } from "./status-badge";

const iconMap = { download: Download, benchmark: TerminalSquare, tts: Mic2, audiobook: FileAudio, whisper: FileText, image: ImageIcon, video: Film, "model-training": PackageCheck, voice: Mic2 };
const toneMap = { queued: "info", running: "success", completed: "success", failed: "danger", cancelled: "warning", stopped: "warning", needs_review: "warning" } as const;

function dateLabel(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function JobCard({ job, compact = false }: { job: UnifiedJob; compact?: boolean }) {
  const Icon = iconMap[job.kind] ?? LoaderCircle;
  const progress = typeof job.progressPercent === "number" ? Math.max(0, Math.min(100, job.progressPercent)) : null;
  return (
    <article className={cn("rounded-lg border border-[#223044] bg-[#0d131c] p-4", compact && "p-3")}>
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-[#223044] bg-[#121a26] text-[#21d4fd]"><Icon className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2"><StatusBadge tone={toneMap[job.status]}>{job.status.replace("_", " ")}</StatusBadge><span className="text-xs uppercase tracking-[0.14em] text-[#617083]">{job.kind.replace("-", " ")}</span></div>
          <h3 className="mt-2 truncate text-sm font-semibold text-[#e6edf5]" title={job.title}>{job.title}</h3>
          {job.subtitle ? <p className="mt-1 line-clamp-2 text-sm text-[#8a98aa]" title={job.subtitle}>{job.subtitle}</p> : null}
          {progress !== null ? <div className="mt-3"><div className="mb-1 flex justify-between gap-3 text-xs text-[#8a98aa]"><span>{job.progressLabel ?? "Progress"}</span><span className="font-mono">{progress.toFixed(progress % 1 === 0 ? 0 : 1)}%</span></div><div className="h-1.5 overflow-hidden rounded-full bg-[#223044]"><div className="h-full rounded-full bg-[#21d4fd]" style={{ width: `${progress}%` }} /></div></div> : null}
          {job.error ? <div className="mt-3 flex gap-2 rounded-md border border-[#fb4b6b]/30 bg-[#fb4b6b]/10 px-3 py-2 text-sm text-rose-100"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" /><span className="line-clamp-3">{job.error}</span></div> : null}
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[#617083]">{job.model ? <span className="truncate">Model: {job.model}</span> : null}<span>{dateLabel(job.updatedAt ?? job.finishedAt ?? job.createdAt)}</span>{job.outputUrl ? <a href={job.outputUrl} className="inline-flex items-center gap-1 text-[#21d4fd] hover:text-cyan-100"><ExternalLink className="h-3.5 w-3.5" />Output</a> : null}</div>
        </div>
      </div>
    </article>
  );
}
