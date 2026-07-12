"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  Activity, Bot, BriefcaseBusiness, CheckCircle2, ChevronDown, Command,
  Database, Home, LogOut, Menu, Search,
  Settings2, Sparkles, Thermometer, Wrench, X, Zap,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { formatBytes, formatNumber } from "@/lib/format";
import type { UnifiedJob } from "@/lib/jobs";
import type { LiveTelemetry } from "@/lib/types";
import type { ApplianceVersion } from "@/lib/version";
import type { ResourceState } from "@/lib/resource-manager";
import { JobCard } from "./job-card";
import { StatusBadge } from "./status-badge";

type JobsPayload = { jobs: UnifiedJob[]; summary: { active: number; queued: number; failed: number; completed: number; total: number } };

const areas = [
  { href: "/", label: "Home", icon: Home, match: ["/"] },
  { href: "/jobs", label: "Work", icon: BriefcaseBusiness, match: ["/jobs", "/outputs"] },
  { href: "/models", label: "Models", icon: Bot, match: ["/models", "/benchmarks", "/keys"] },
  { href: "/studio/speech", label: "Studio", icon: Sparkles, match: ["/studio", "/tts", "/whisper", "/images", "/video", "/research"] },
  { href: "/settings", label: "System", icon: Settings2, match: ["/system", "/settings", "/timeline", "/logs"] },
];

const contextLinks: Record<string, Array<{ href: string; label: string }>> = {
  Home: [{ href: "/", label: "Command center" }],
  Work: [{ href: "/jobs", label: "Jobs" }, { href: "/outputs", label: "Outputs" }],
  Models: [{ href: "/models", label: "Library" }, { href: "/benchmarks", label: "Benchmarks" }, { href: "/keys", label: "API access" }],
  Studio: [{ href: "/studio/speech", label: "Speech" }, { href: "/studio/audiobooks", label: "Audiobooks" }, { href: "/studio/presentations", label: "Presentations" }, { href: "/studio/voices", label: "Voice Library" }, { href: "/studio/training", label: "Training" }, { href: "/whisper", label: "Transcription" }, { href: "/images", label: "Images" }, { href: "/video", label: "Video" }, { href: "/research", label: "Research" }],
  System: [{ href: "/settings", label: "Health & controls" }, { href: "/system/metrics", label: "Metrics" }, { href: "/timeline", label: "Timeline" }, { href: "/logs", label: "Logs" }],
};

function isPathActive(pathname: string, href: string) { return href === "/" ? pathname === "/" : pathname.startsWith(href); }
function shortModelName(model?: string) { return !model || model === "unknown" ? "No model" : (model.split("/").pop() ?? model).replace(/\.gguf$/i, ""); }
function readinessTone(status?: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "ready" || status === "busy") return "success";
  if (status === "starting" || status === "releasing" || status === "restoring") return "warning";
  if (status === "failed") return "danger";
  if (status === "unloaded") return "info";
  return status ? "info" : "neutral";
}

function IconButton({ label, onClick, children, active }: { label: string; onClick: () => void; children: React.ReactNode; active?: boolean }) {
  return <button type="button" aria-label={label} title={label} onClick={onClick} className={cn("inline-flex h-9 w-9 items-center justify-center rounded-md text-[#8a98aa] transition hover:bg-[#182231] hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#21d4fd]", active && "bg-[#182231] text-[#21d4fd]")}>{children}</button>;
}

function ShellNav({ pathname, mobile, close }: { pathname: string; mobile?: boolean; close?: () => void }) {
  const activeArea = areas.find((area) => area.match.some((path) => isPathActive(pathname, path))) ?? areas[0];
  return <>
    <div className="flex h-14 items-center gap-3 px-4">
      <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[#21d4fd]/12 text-[#21d4fd]"><Wrench className="h-4 w-4" /></div>
      <div className="min-w-0"><div className="truncate text-sm font-semibold text-white">GPU45</div><div className="text-xs text-[#718096]">Appliance console</div></div>
      {mobile ? <div className="ml-auto"><IconButton label="Close navigation" onClick={() => close?.()}><X className="h-4 w-4" /></IconButton></div> : null}
    </div>
    <nav aria-label="Primary navigation" className="space-y-1 px-2 py-3">
      {areas.map((area) => { const Icon = area.icon; const active = area.label === activeArea.label; return <Link onClick={close} key={area.label} href={area.href} className={cn("flex h-10 items-center gap-3 rounded-md px-3 text-sm transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#21d4fd]", active ? "bg-[#172331] font-medium text-white" : "text-[#8a98aa] hover:bg-[#121a26] hover:text-white")}><Icon className={cn("h-4 w-4", active ? "text-[#21d4fd]" : "text-[#617083]")} /><span>{area.label}</span></Link>; })}
    </nav>
    <div className="mx-3 border-t border-[#1b2736] pt-4">
      <div className="px-2 text-xs font-medium text-[#617083]">{activeArea.label}</div>
      <nav aria-label={`${activeArea.label} navigation`} className="mt-2 space-y-0.5">
        {contextLinks[activeArea.label].map((item) => <Link onClick={close} key={item.href} href={item.href} className={cn("block rounded-md px-2 py-2 text-sm transition", isPathActive(pathname, item.href) ? "text-[#21d4fd]" : "text-[#8a98aa] hover:bg-[#121a26] hover:text-white")}>{item.label}</Link>)}
      </nav>
    </div>
  </>;
}

function StatusBar({ initial, onJobs, onMenu, jobs }: { initial: LiveTelemetry; onJobs: () => void; onMenu: () => void; jobs: JobsPayload | null }) {
  const [live, setLive] = useState(initial);
  const [connected, setConnected] = useState(false);
  const [resources, setResources] = useState<ResourceState | null>(null);
  const [telemetryOpen, setTelemetryOpen] = useState(false);
  useEffect(() => {
    const source = new EventSource("/api/events?topics=telemetry,resources");
    source.addEventListener("telemetry", (event) => { setLive(JSON.parse((event as MessageEvent).data) as LiveTelemetry); setConnected(true); });
    source.addEventListener("resources", (event) => { setResources(JSON.parse((event as MessageEvent).data) as ResourceState); });
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, []);
  const s = live.system; const provider = live.provider; const owner = resources?.owner?.kind ?? ((jobs?.summary.active ?? 0) > 0 ? "working" : "idle");
  return <header className="sticky top-0 z-30 border-b border-[#1b2736] bg-[#0b1119]/95 backdrop-blur">
    <div className="flex h-14 min-w-0 items-center gap-2 px-3 lg:px-4">
      <div className="lg:hidden"><IconButton label="Open navigation" onClick={onMenu}><Menu className="h-4 w-4" /></IconButton></div>
      <div className="flex min-w-0 items-center gap-2"><StatusBadge tone={readinessTone(provider.status)}>{provider.status ?? "connecting"}</StatusBadge><span className={cn("h-1.5 w-1.5 rounded-full", connected ? "bg-[#36fba1]" : "bg-[#fb4b6b]")} /><span className="hidden max-w-[20rem] truncate text-sm text-[#cdd7e3] sm:block">{shortModelName(provider.model)}</span></div>
      <div className="ml-auto flex min-w-0 items-center gap-1">
        <button onClick={() => setTelemetryOpen((value) => !value)} className="hidden items-center gap-3 rounded-md px-2 py-1.5 text-xs text-[#8a98aa] transition hover:bg-[#182231] hover:text-white md:flex">
          <span><Thermometer className="mr-1 inline h-3.5 w-3.5 text-[#fbbf24]" />{s.gpuTempJunctionC == null ? "n/a" : `${formatNumber(s.gpuTempJunctionC, 0)} C`}</span>
          <span><Database className="mr-1 inline h-3.5 w-3.5 text-[#a78bfa]" />{s.vramUsedBytes == null ? "n/a" : formatBytes(s.vramUsedBytes)}</span>
          <span className="hidden xl:inline"><Zap className="mr-1 inline h-3.5 w-3.5 text-[#fbbf24]" />{s.gpuPowerW == null ? "n/a" : `${formatNumber(s.gpuPowerW, 0)} W`}</span>
          <ChevronDown className={cn("h-3.5 w-3.5", telemetryOpen && "rotate-180")} />
        </button>
        <button onClick={onJobs} className="relative flex h-9 items-center gap-2 rounded-md px-2.5 text-sm text-[#8a98aa] hover:bg-[#182231] hover:text-white"><Activity className="h-4 w-4" /><span className="hidden sm:inline">{owner}</span>{(jobs?.summary.active ?? 0) > 0 ? <span className="rounded-full bg-[#21d4fd] px-1.5 text-[10px] font-semibold text-[#071018]">{jobs?.summary.active}</span> : null}</button>
        <IconButton label="Open command palette" onClick={() => window.dispatchEvent(new CustomEvent("gpu45:commands"))}><Command className="h-4 w-4" /></IconButton>
      </div>
    </div>
    {telemetryOpen ? <div className="absolute right-3 top-[3.35rem] grid w-[min(28rem,calc(100vw-1.5rem))] grid-cols-2 gap-3 rounded-lg border border-[#223044] bg-[#101822] p-4 shadow-2xl sm:grid-cols-3">
      {[['Junction', s.gpuTempJunctionC == null ? 'n/a' : `${formatNumber(s.gpuTempJunctionC, 1)} C`], ['VRAM', s.vramUsedBytes == null ? 'n/a' : formatBytes(s.vramUsedBytes)], ['Power', s.gpuPowerW == null ? 'n/a' : `${formatNumber(s.gpuPowerW, 0)} W`], ['GPU busy', s.gpuUsage == null ? 'n/a' : `${formatNumber(s.gpuUsage, 0)}%`], ['Fan', s.fanRpm == null ? 'n/a' : `${formatNumber(s.fanRpm, 0)} rpm`], ['Queue', `${resources?.queue.length ?? 0} waiting`]].map(([label, value]) => <div key={label}><div className="text-xs text-[#718096]">{label}</div><div className="mt-1 font-mono text-sm text-white">{value}</div></div>)}
    </div> : null}
  </header>;
}

function CommandPalette({ close }: { close: () => void }) {
  const router = useRouter(); const [query, setQuery] = useState("");
  const commands = useMemo(() => areas.flatMap((area) => [{ href: area.href, label: `Open ${area.label}`, group: "Navigate" }, ...contextLinks[area.label].map((item) => ({ href: item.href, label: item.label, group: area.label }))]).filter((item, index, all) => all.findIndex((candidate) => candidate.href === item.href) === index), []);
  const visible = commands.filter((item) => `${item.label} ${item.group}`.toLowerCase().includes(query.toLowerCase())).slice(0, 10);
  return <div className="fixed inset-0 z-50 bg-black/65 p-4 pt-[12vh]" onMouseDown={close}><div role="dialog" aria-modal="true" aria-label="Command palette" className="mx-auto max-w-xl overflow-hidden rounded-xl border border-[#2a3a4f] bg-[#101822] shadow-2xl" onMouseDown={(event) => event.stopPropagation()}>
    <div className="flex items-center gap-3 border-b border-[#223044] px-4"><Search className="h-4 w-4 text-[#617083]" /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") close(); }} placeholder="Go to a page or workflow..." className="h-14 min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-[#617083]" /></div>
    <div className="max-h-80 overflow-y-auto p-2">{visible.map((item) => <button key={item.href} onClick={() => { router.push(item.href); close(); }} className="flex w-full items-center justify-between rounded-md px-3 py-2.5 text-left text-sm text-[#cdd7e3] hover:bg-[#182331] hover:text-white"><span>{item.label}</span><span className="text-xs text-[#617083]">{item.group}</span></button>)}{visible.length === 0 ? <div className="px-3 py-8 text-center text-sm text-[#718096]">No matching destination</div> : null}</div>
  </div></div>;
}

export function AppChrome({ children, version, initialTelemetry }: { children: React.ReactNode; version: ApplianceVersion; initialTelemetry: LiveTelemetry }) {
  const pathname = usePathname(); const [mobileNav, setMobileNav] = useState(false); const [jobsOpen, setJobsOpen] = useState(false); const [commandsOpen, setCommandsOpen] = useState(false); const [accountOpen, setAccountOpen] = useState(false); const [jobs, setJobs] = useState<JobsPayload | null>(null);
  useEffect(() => { const listener = () => setCommandsOpen(true); window.addEventListener("gpu45:commands", listener); const key = (event: KeyboardEvent) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); setCommandsOpen(true); } }; window.addEventListener("keydown", key); return () => { window.removeEventListener("gpu45:commands", listener); window.removeEventListener("keydown", key); }; }, []);
  useEffect(() => { const source = new EventSource("/api/events?topics=operational-jobs"); source.addEventListener("operational-jobs", (event) => setJobs(JSON.parse((event as MessageEvent).data) as JobsPayload)); return () => source.close(); }, []);
  if (pathname === "/login") return children;
  const drawerJobs = jobs?.jobs.filter((job) => ["queued", "running", "paused", "failed", "needs_review"].includes(job.status)).slice(0, 8) ?? [];
  return <div className="min-h-screen overflow-x-hidden bg-[#070a0f] text-[#e6edf5]">
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-56 border-r border-[#1b2736] bg-[#0a0f17] lg:block"><ShellNav pathname={pathname} /><div className="absolute inset-x-2 bottom-3"><button onClick={() => setAccountOpen((value) => !value)} className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm text-[#8a98aa] hover:bg-[#121a26] hover:text-white"><div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#172331] text-xs text-[#21d4fd]">H</div><span className="min-w-0 flex-1 truncate">hendo420</span><ChevronDown className="h-3.5 w-3.5" /></button>{accountOpen ? <div className="absolute bottom-12 left-0 right-0 rounded-lg border border-[#223044] bg-[#101822] p-2 shadow-xl"><div className="px-2 py-1.5 text-xs text-[#617083]">v{version.version} · {version.commit.slice(0, 8)}</div><button onClick={async () => { await fetch("/api/auth/logout", { method: "POST" }); window.location.assign("/login"); }} className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-[#8a98aa] hover:bg-[#182331] hover:text-white"><LogOut className="h-4 w-4" />Sign out</button></div> : null}</div></aside>
    {mobileNav ? <div className="fixed inset-0 z-50 bg-black/60 lg:hidden" onClick={() => setMobileNav(false)}><aside className="h-full w-[min(18rem,86vw)] border-r border-[#223044] bg-[#0a0f17]" onClick={(event) => event.stopPropagation()}><ShellNav pathname={pathname} mobile close={() => setMobileNav(false)} /></aside></div> : null}
    <div className="min-w-0 lg:pl-56"><StatusBar initial={initialTelemetry} jobs={jobs} onMenu={() => setMobileNav(true)} onJobs={() => setJobsOpen(true)} /><main className="mx-auto w-full max-w-[1560px] px-4 py-5 sm:px-6">{children}</main></div>
    {jobsOpen ? <div className="fixed inset-0 z-50 bg-black/55" onClick={() => setJobsOpen(false)}><aside className="ml-auto flex h-full w-[min(34rem,94vw)] flex-col border-l border-[#223044] bg-[#0b1119] shadow-2xl" onClick={(event) => event.stopPropagation()}><div className="flex h-14 items-center justify-between border-b border-[#223044] px-4"><div><div className="font-semibold text-white">Work</div><div className="text-xs text-[#718096]">Active jobs and attention</div></div><IconButton label="Close jobs" onClick={() => setJobsOpen(false)}><X className="h-4 w-4" /></IconButton></div><div className="flex-1 space-y-3 overflow-y-auto p-4">{drawerJobs.map((job) => <JobCard key={job.id} job={job} compact />)}{drawerJobs.length === 0 ? <div className="py-16 text-center"><CheckCircle2 className="mx-auto h-8 w-8 text-[#36fba1]" /><div className="mt-3 text-sm text-white">No active work</div><div className="mt-1 text-xs text-[#718096]">The unified queue is clear.</div></div> : null}</div><div className="border-t border-[#223044] p-3"><Link onClick={() => setJobsOpen(false)} href="/jobs" className="flex h-10 items-center justify-center rounded-md bg-[#21d4fd] text-sm font-semibold text-[#061018] hover:bg-[#63e4ff]">Open Work</Link></div></aside></div> : null}
    {commandsOpen ? <CommandPalette close={() => setCommandsOpen(false)} /> : null}
  </div>;
}
