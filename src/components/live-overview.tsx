"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Activity, AlertTriangle, ArrowRight, Bot, BriefcaseBusiness, CheckCircle2, Database, HardDrive, ImageIcon, Mic2, Sparkles, Thermometer, Video, Zap } from "lucide-react";
import { OperationalChart } from "./operational-chart";
import { StatusBadge } from "./status-badge";
import { formatBytes, formatNumber } from "@/lib/format";
import type { DashboardSnapshot, LiveTelemetry, MetricSeries } from "@/lib/types";
import type { UnifiedJob } from "@/lib/jobs";

const MAX_POINTS = 180;
type JobsPayload = { summary: { active: number; queued: number; failed: number; completed: number; total: number }; jobs: UnifiedJob[] };

function append(series: MetricSeries, timestamp: string, value: number | null): MetricSeries {
  if (value === null || !Number.isFinite(value)) return series;
  return { ...series, points: [...series.points, { timestamp, value }].slice(-MAX_POINTS) };
}

function updateCharts(charts: DashboardSnapshot["charts"], live: LiveTelemetry): DashboardSnapshot["charts"] {
  const s = live.system; const gib = 1024 ** 3;
  return { ...charts,
    gpuTempEdge: append(charts.gpuTempEdge, live.collectedAt, s.gpuTempEdgeC), gpuTempJunction: append(charts.gpuTempJunction, live.collectedAt, s.gpuTempJunctionC), gpuTempMemory: append(charts.gpuTempMemory, live.collectedAt, s.gpuTempMemoryC),
    gpuPower: append(charts.gpuPower, live.collectedAt, s.gpuPowerW), gpuUsage: append(charts.gpuUsage, live.collectedAt, s.gpuUsage), tokensPerSecond: append(charts.tokensPerSecond, live.collectedAt, live.provider.tokensPerSecond),
    vramUsed: append(charts.vramUsed, live.collectedAt, s.vramUsedBytes === null ? null : s.vramUsedBytes / gib), vramTotal: append(charts.vramTotal, live.collectedAt, s.vramTotalBytes === null ? null : s.vramTotalBytes / gib), vramFree: append(charts.vramFree, live.collectedAt, s.vramUsedBytes === null || s.vramTotalBytes === null ? null : (s.vramTotalBytes - s.vramUsedBytes) / gib),
    cpuUsage: append(charts.cpuUsage, live.collectedAt, s.cpuUsage), ramUsage: append(charts.ramUsage, live.collectedAt, s.ramUsedBytes / gib), diskUsed: append(charts.diskUsed, live.collectedAt, s.diskUsedBytes / gib), diskFree: append(charts.diskFree, live.collectedAt, s.diskFreeBytes / gib), fanPwm: append(charts.fanPwm, live.collectedAt, s.fanPwm), fanRpm: append(charts.fanRpm, live.collectedAt, s.fanRpm),
  };
}

function Metric({ label, value, detail, icon: Icon, tone }: { label: string; value: string; detail: string; icon: React.ComponentType<{ className?: string }>; tone: string }) {
  return <article className="rounded-lg bg-[#0d141e] p-4"><div className="flex items-center justify-between"><span className="text-sm text-[#8a98aa]">{label}</span><Icon className={`h-4 w-4 ${tone}`} /></div><div className="mt-3 font-mono text-2xl font-medium text-white">{value}</div><div className="mt-1 text-xs text-[#617083]">{detail}</div></article>;
}

function operationalState(live: LiveTelemetry, activeJob?: UnifiedJob) {
  if (live.provider.status === "failed") return { title: "Appliance needs attention", body: "The provider proxy or LLM process failed. Open System for diagnostics.", tone: "danger" as const, icon: AlertTriangle };
  if (activeJob) return { title: `${activeJob.kind === "audiobook" ? "Audio Studio" : "Studio"} is using the appliance`, body: activeJob.waitReason || `${activeJob.title} is ${activeJob.status}. The LLM will be restored when the workflow releases the GPU.`, tone: "warning" as const, icon: Activity };
  if (live.provider.status === "releasing") return { title: "Preparing the GPU", body: "The LLM is releasing GPU memory for the next queued workflow.", tone: "warning" as const, icon: Bot };
  if (live.provider.status === "restoring") return { title: "Restoring the LLM", body: "The previous model is loading and will become available automatically.", tone: "warning" as const, icon: Bot };
  if (live.provider.status === "starting") return { title: "Starting the LLM", body: "The selected model is loading for an interactive request.", tone: "warning" as const, icon: Bot };
  if (live.provider.status === "unloaded") return { title: "Ready on demand", body: "The GPU is free and the selected LLM will load automatically with the next Codex request.", tone: "info" as const, icon: Bot };
  return { title: "Ready for Codex", body: "The provider is online, the queue is clear, and the active model can accept requests.", tone: "success" as const, icon: CheckCircle2 };
}

export function LiveOverview({ initial }: { initial: DashboardSnapshot; endpoint: { allowAnonymous: boolean; visibleModels: number; endpointBase: string } }) {
  const [live, setLive] = useState<LiveTelemetry>({ collectedAt: initial.collectedAt, provider: initial.provider, system: initial.system });
  const [charts, setCharts] = useState(initial.charts); const [jobs, setJobs] = useState<JobsPayload | null>(null);
  useEffect(() => { const source = new EventSource("/api/live"); source.addEventListener("telemetry", (event) => { const next = JSON.parse((event as MessageEvent).data) as LiveTelemetry; setLive(next); setCharts((current) => updateCharts(current, next)); }); return () => source.close(); }, []);
  useEffect(() => { let cancelled = false; const load = async () => { try { const response = await fetch("/api/jobs", { cache: "no-store" }); if (response.ok && !cancelled) setJobs(await response.json() as JobsPayload); } catch { if (!cancelled) setJobs(null); } }; void load(); const timer = window.setInterval(() => void load(), 5000); return () => { cancelled = true; window.clearInterval(timer); }; }, []);
  const s = live.system; const activeJob = jobs?.jobs.find((job) => ["running", "queued", "paused"].includes(job.status)); const state = operationalState(live, activeJob); const StateIcon = state.icon;
  const latestFailures = jobs?.jobs.filter((job) => job.status === "failed" || job.status === "needs_review").slice(0, 3) ?? [];
  const vramFree = s.vramUsedBytes !== null && s.vramTotalBytes !== null ? s.vramTotalBytes - s.vramUsedBytes : null;
  return <div className="space-y-5">
    <section className="rounded-xl bg-[#0d141e] p-5 sm:p-6"><div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between"><div className="flex min-w-0 gap-4"><div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-lg bg-[#172331]"><StateIcon className={state.tone === "success" ? "h-6 w-6 text-[#36fba1]" : state.tone === "danger" ? "h-6 w-6 text-[#fb4b6b]" : "h-6 w-6 text-[#fbbf24]"} /></div><div><div className="flex flex-wrap items-center gap-2"><h1 className="text-xl font-semibold text-white sm:text-2xl">{state.title}</h1><StatusBadge tone={state.tone}>{live.provider.status}</StatusBadge></div><p className="mt-1 max-w-2xl text-sm leading-6 text-[#8a98aa]">{state.body}</p></div></div><div className="flex shrink-0 gap-2"><Link href="/models" className="inline-flex h-10 items-center gap-2 rounded-md border border-[#2a3a4f] px-3 text-sm text-[#cdd7e3] hover:bg-[#172331]">Switch model</Link><Link href="/jobs" className="inline-flex h-10 items-center gap-2 rounded-md bg-[#21d4fd] px-3 text-sm font-semibold text-[#071018] hover:bg-[#63e4ff]">Open Work<ArrowRight className="h-4 w-4" /></Link></div></div>
      {activeJob ? <div className="mt-5 rounded-lg bg-[#080d14] p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><div className="flex items-center gap-2 text-xs text-[#8a98aa]"><BriefcaseBusiness className="h-3.5 w-3.5 text-[#21d4fd]" />Active work</div><div className="mt-2 truncate text-sm font-medium text-white">{activeJob.title}</div><div className="mt-1 text-xs text-[#617083]">{activeJob.progressLabel ?? activeJob.stage ?? activeJob.status}{activeJob.etaSeconds ? ` · about ${Math.ceil(activeJob.etaSeconds / 60)} min remaining` : ""}</div></div><Link href="/jobs" className="text-sm text-[#21d4fd] hover:text-white">Manage</Link></div>{typeof activeJob.progressPercent === "number" ? <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#223044]"><div className="h-full rounded-full bg-[#21d4fd]" style={{ width: `${Math.max(0, Math.min(100, activeJob.progressPercent))}%` }} /></div> : null}</div> : null}
    </section>
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Junction" value={s.gpuTempJunctionC == null ? "n/a" : `${formatNumber(s.gpuTempJunctionC, 0)} C`} detail={`Edge ${s.gpuTempEdgeC == null ? "n/a" : `${formatNumber(s.gpuTempEdgeC, 0)} C`}`} icon={Thermometer} tone="text-[#fbbf24]" /><Metric label="VRAM" value={s.vramUsedBytes == null ? "n/a" : formatBytes(s.vramUsedBytes)} detail={vramFree == null ? "Sensor unavailable" : `${formatBytes(vramFree)} available`} icon={Database} tone="text-[#a78bfa]" /><Metric label="Power" value={s.gpuPowerW == null ? "n/a" : `${formatNumber(s.gpuPowerW, 0)} W`} detail={`${s.gpuUsage == null ? "n/a" : `${formatNumber(s.gpuUsage, 0)}%`} GPU utilization`} icon={Zap} tone="text-[#fbbf24]" /><Metric label="Storage" value={formatBytes(s.diskFreeBytes)} detail={`${formatBytes(s.diskUsedBytes)} used`} icon={HardDrive} tone="text-[#36fba1]" /></section>
    <section className="grid gap-4 xl:grid-cols-[1.5fr_1fr]"><div className="rounded-xl bg-[#0d141e] p-4 sm:p-5"><div className="flex items-center justify-between"><div><h2 className="font-semibold text-white">Recent operating envelope</h2><p className="mt-1 text-sm text-[#718096]">Temperature, utilization, and throughput</p></div><Link href="/settings" className="text-sm text-[#21d4fd]">System details</Link></div><div className="mt-4 grid gap-4 2xl:grid-cols-2"><OperationalChart title="Thermals" subtitle="Edge and junction" series={[charts.gpuTempEdge, charts.gpuTempJunction]} /><OperationalChart title="Activity" subtitle="GPU usage and tokens/sec" series={[charts.gpuUsage, charts.tokensPerSecond]} /></div></div>
      <div className="space-y-4"><section className="rounded-xl bg-[#0d141e] p-5"><div className="flex items-center justify-between"><h2 className="font-semibold text-white">Attention</h2><span className="text-xs text-[#617083]">{latestFailures.length} recent</span></div>{latestFailures.length ? <div className="mt-3 space-y-2">{latestFailures.map((job) => <Link href="/jobs" key={job.id} className="block rounded-md bg-[#15151a] px-3 py-2.5 hover:bg-[#1b1b22]"><div className="truncate text-sm text-[#f3c4cd]">{job.title}</div><div className="mt-1 line-clamp-2 text-xs text-[#8a6f76]">{job.userMessage ?? job.error ?? "Review this job"}</div></Link>)}</div> : <div className="mt-5 flex items-center gap-3 text-sm text-[#8a98aa]"><CheckCircle2 className="h-5 w-5 text-[#36fba1]" />No jobs need attention.</div>}</section>
      <section className="rounded-xl bg-[#0d141e] p-5"><h2 className="font-semibold text-white">Quick actions</h2><div className="mt-3 grid grid-cols-2 gap-2">{[["Speech", "/tts", Mic2], ["Image", "/images", ImageIcon], ["Video", "/video", Video], ["All Studio", "/tts", Sparkles]].map(([label, href, Icon]) => { const QuickIcon = Icon as typeof Mic2; return <Link key={label as string} href={href as string} className="flex items-center gap-2 rounded-md bg-[#121a26] px-3 py-2.5 text-sm text-[#cdd7e3] hover:bg-[#172331] hover:text-white"><QuickIcon className="h-4 w-4 text-[#21d4fd]" />{label as string}</Link>; })}</div></section></div>
    </section>
  </div>;
}
