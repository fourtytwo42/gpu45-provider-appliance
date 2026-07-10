"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Activity, Bot, BriefcaseBusiness, Cpu, Database, FileSearch, FileText, Film, Gauge, HardDriveDownload, ImageIcon, KeyRound, Library, LogOut, Logs, Mic2, RadioTower, ScrollText, Settings2, SquareTerminal, Thermometer, Wrench, Zap } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatBytes, formatNumber } from "@/lib/format";
import type { LiveTelemetry } from "@/lib/types";
import type { ApplianceVersion } from "@/lib/version";
import type { ResourceState } from "@/lib/resource-manager";
import { MetricTile } from "./metric-tile";
import { StatusBadge } from "./status-badge";

type JobsSummary = { active: number; queued: number; failed: number; completed: number; total: number };

const navGroups = [
  { label: "Command Center", items: [{ href: "/", label: "Overview", icon: Gauge }, { href: "/jobs", label: "Jobs", icon: BriefcaseBusiness }, { href: "/outputs", label: "Outputs", icon: Library }] },
  { label: "LLM Provider", items: [{ href: "/models", label: "Models", icon: HardDriveDownload }, { href: "/benchmarks", label: "Benchmarks", icon: SquareTerminal }, { href: "/keys", label: "Keys", icon: KeyRound }] },
  { label: "Audio Studio", items: [{ href: "/tts", label: "TTS & Audiobooks", icon: Mic2 }, { href: "/whisper", label: "Whisper", icon: FileText }] },
  { label: "Media Studio", items: [{ href: "/images", label: "Images", icon: ImageIcon }, { href: "/video", label: "Video", icon: Film }] },
  { label: "Research", items: [{ href: "/research", label: "Search & Scrape", icon: FileSearch }] },
  { label: "System", items: [{ href: "/timeline", label: "Timeline", icon: ScrollText }, { href: "/logs", label: "Logs", icon: Logs }, { href: "/settings", label: "Settings", icon: Settings2 }] },
];

function shortModelName(model?: string): string {
  if (!model || model === "unknown") return "No model";
  const clean = model.split(/[\/]/).pop() ?? model;
  return clean.replace(/\.gguf$/i, "");
}

function readinessTone(status?: string): "success" | "warning" | "danger" | "info" | "neutral" {
  if (status === "idle" || status === "generating") return "success";
  if (status === "loading" || status === "restarting") return "warning";
  if (status === "error" || status === "offline") return "danger";
  if (status) return "info";
  return "neutral";
}

function formatTemp(value: number | null | undefined): string { return value == null ? "n/a" : `${formatNumber(value, 0)} C`; }
function formatWatts(value: number | null | undefined): string { return value == null ? "n/a" : `${formatNumber(value, 0)} W`; }
function formatRpm(value: number | null | undefined): string { return value == null ? "n/a" : `${new Intl.NumberFormat("en-US").format(Math.round(value))} rpm`; }

function TopStatusBar({ initial }: { initial: LiveTelemetry }) {
  const [live, setLive] = useState<LiveTelemetry>(initial);
  const [connected, setConnected] = useState(false);
  const [jobs, setJobs] = useState<JobsSummary | null>(null);
  const [resources, setResources] = useState<ResourceState | null>(null);

  useEffect(() => {
    const source = new EventSource("/api/live");
    source.addEventListener("telemetry", (event) => {
      setLive(JSON.parse((event as MessageEvent).data) as LiveTelemetry);
      setConnected(true);
    });
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadResources() {
      try { const response = await fetch("/api/resources/state", { cache: "no-store" }); const value = await response.json() as ResourceState; if (!cancelled) setResources(value); }
      catch { if (!cancelled) setResources(null); }
    }
    void loadResources(); const timer = window.setInterval(() => void loadResources(), 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadJobs() {
      try {
        const response = await fetch("/api/jobs", { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json() as { summary?: JobsSummary };
        if (!cancelled) setJobs(payload.summary ?? null);
      } catch {
        if (!cancelled) setJobs(null);
      }
    }
    void loadJobs();
    const timer = window.setInterval(() => void loadJobs(), 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const system = live?.system;
  const provider = live?.provider;
  const vramDetail = system?.vramUsedBytes != null && system?.vramTotalBytes != null ? `${formatBytes(system.vramUsedBytes)} / ${formatBytes(system.vramTotalBytes)}` : "sensor unavailable";
  const activeJobs = (jobs?.active ?? 0) + (provider?.activeRequests ?? 0);
  const owner = resources?.owner?.kind ?? (activeJobs ? "working" : "idle");

  return (
    <div className="border-b border-[#223044] bg-[#0d131c]/95 px-3 py-3 backdrop-blur xl:px-5">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1.4fr_repeat(5,minmax(132px,1fr))]">
        <div className="rounded-lg border border-[#223044] bg-[#070a0f] px-3 py-2">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2"><StatusBadge tone={readinessTone(provider?.status)}>{provider?.status ?? "connecting"}</StatusBadge><span className={cn("h-2 w-2 rounded-full", connected ? "bg-[#36fba1]" : "bg-[#fb4b6b]")} /></div>
              <div className="mt-1 truncate font-mono text-sm text-[#e6edf5]" title={provider?.model}>{shortModelName(provider?.model)}</div>
            </div>
            <Bot className="h-5 w-5 shrink-0 text-[#21d4fd]" />
          </div>
        </div>
        <MetricTile label="Junction" value={formatTemp(system?.gpuTempJunctionC)} detail="thermal guard" icon={Thermometer} tone={(system?.gpuTempJunctionC ?? 0) >= 90 ? "rose" : "amber"} />
        <MetricTile label="VRAM" value={system?.vramUsedBytes == null ? "n/a" : formatBytes(system.vramUsedBytes)} detail={vramDetail} icon={Database} tone="violet" />
        <MetricTile label="Power" value={formatWatts(system?.gpuPowerW)} detail="board draw" icon={Zap} tone="amber" />
        <MetricTile label="Fan" value={formatRpm(system?.fanRpm)} detail={`PWM ${system?.fanPwm ?? "n/a"}`} icon={Cpu} tone="cyan" />
        <MetricTile label="GPU owner" value={owner.toUpperCase()} detail={`${activeJobs} active / ${resources?.queue.length ?? 0} waiting`} icon={Activity} tone={owner !== "idle" ? "green" : "slate"} />
      </div>
    </div>
  );
}

export function AppChrome({ children, version, initialTelemetry }: { children: React.ReactNode; version: ApplianceVersion; initialTelemetry: LiveTelemetry }) {
  const pathname = usePathname();
  const activeGroup = useMemo(() => navGroups.find((group) => group.items.some((item) => item.href === pathname || (item.href !== "/" && pathname.startsWith(item.href))))?.label ?? "Command Center", [pathname]);
  if (pathname === "/login") return children;
  return (
    <div className="min-h-screen bg-[#070a0f] text-[#e6edf5]">
      <div className="grid min-h-screen lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="border-b border-[#223044] bg-[#0a0f17]/95 lg:sticky lg:top-0 lg:h-screen lg:border-b-0 lg:border-r">
          <div className="flex h-full flex-col">
            <div className="border-b border-[#223044] px-4 py-4">
              <div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-lg border border-[#21d4fd]/40 bg-[#21d4fd]/10 text-[#21d4fd]"><Wrench className="h-5 w-5" /></div><div className="min-w-0"><div className="truncate text-sm font-semibold tracking-wide text-white">GPU45 Appliance</div><div className="truncate text-xs text-[#8a98aa]">{activeGroup}</div></div></div>
            </div>
            <nav className="flex gap-3 overflow-x-auto px-3 py-3 lg:block lg:flex-1 lg:space-y-5 lg:overflow-y-auto lg:px-3 lg:py-4">
              {navGroups.map((group) => (
                <div key={group.label} className="min-w-[210px] lg:min-w-0">
                  <div className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#617083]">{group.label}</div>
                  <div className="space-y-1">
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
                      return <Link key={item.href} href={item.href} className={cn("group flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition", active ? "border-[#21d4fd]/35 bg-[#21d4fd]/10 text-[#e6edf5] shadow-[inset_3px_0_0_rgba(33,212,253,0.9)]" : "border-transparent text-[#8a98aa] hover:border-[#223044] hover:bg-[#121a26] hover:text-[#e6edf5]")}><Icon className={cn("h-4 w-4 shrink-0", active ? "text-[#21d4fd]" : "text-[#617083] group-hover:text-[#21d4fd]")} /><span className="truncate">{item.label}</span></Link>;
                    })}
                  </div>
                </div>
              ))}
            </nav>
            <div className="hidden border-t border-[#223044] p-3 text-xs text-[#617083] lg:block">
              <div className="flex items-center gap-2"><RadioTower className="h-3.5 w-3.5 text-[#36fba1]" /> Persistent bare-metal console</div>
              <div className="mt-1 truncate font-mono text-[10px]" title={version.commit}>v{version.version} · {version.commit.slice(0, 12)}</div>
              <button type="button" onClick={async () => { await fetch("/api/auth/logout", { method: "POST" }); window.location.assign("/login"); }} className="mt-3 flex w-full items-center gap-2 border border-[#223044] px-2 py-2 text-left text-[#8a98aa] hover:bg-[#121a26] hover:text-white"><LogOut className="h-3.5 w-3.5" /> Sign out</button>
            </div>
          </div>
        </aside>
        <div className="min-w-0"><TopStatusBar initial={initialTelemetry} /><main className="mx-auto w-full max-w-[1680px] px-3 py-4 lg:px-5">{children}</main></div>
      </div>
    </div>
  );
}
