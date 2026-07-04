"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, LoaderCircle, Pause, Play, RefreshCw, Search } from "lucide-react";
import type { LogSource } from "@/lib/logs";

const sources: Array<{ value: LogSource; label: string }> = [
  { value: "provider", label: "Provider" }, { value: "proxy", label: "Responses proxy" }, { value: "app", label: "Web app" }, { value: "worker", label: "Telemetry worker" }, { value: "fan", label: "Fan controller" },
];

export function LiveLogs({ initialLines }: { initialLines: string[] }) {
  const [source, setSource] = useState<LogSource>("provider");
  const [lines, setLines] = useState(initialLines);
  const [filter, setFilter] = useState("");
  const [paused, setPaused] = useState(false);
  const [loading, setLoading] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(new Date());
  const refresh = useCallback(async () => {
    setLoading(true);
    const response = await fetch(`/api/logs?source=${source}&limit=500`, { cache: "no-store" });
    if (response.ok) { const payload = await response.json(); setLines(payload.lines); setUpdatedAt(new Date(payload.collectedAt)); }
    setLoading(false);
  }, [source]);
  useEffect(() => { const timer = setTimeout(() => void refresh(), 0); return () => clearTimeout(timer); }, [refresh]);
  useEffect(() => { if (paused) return; const timer = setInterval(() => void refresh(), 3000); return () => clearInterval(timer); }, [paused, refresh]);
  const visible = useMemo(() => filter ? lines.filter((line) => line.toLowerCase().includes(filter.toLowerCase())) : lines, [filter, lines]);
  function save() { const blob = new Blob([visible.join("\n")], { type: "text/plain" }); const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = `gpu45-${source}-${new Date().toISOString()}.log`; link.click(); URL.revokeObjectURL(link.href); }
  return <section className="border border-white/10 bg-[#0a1119]">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 p-4"><div><h1 className="text-lg font-semibold text-white">Service journals</h1><p className="mt-1 text-xs text-slate-500">Live systemd output from the bare-metal appliance.</p></div><div className="flex items-center gap-2 text-[11px] text-slate-600"><span className="h-2 w-2 bg-emerald-400" />updated {updatedAt.toLocaleTimeString()}</div></div>
    <div className="flex flex-wrap gap-2 border-b border-white/10 p-3">{sources.map((item) => <button key={item.value} onClick={() => setSource(item.value)} className={`px-3 py-1.5 text-xs ${source === item.value ? "bg-cyan-400/15 text-cyan-200 ring-1 ring-cyan-400/40" : "bg-white/5 text-slate-400 hover:text-white"}`}>{item.label}</button>)}</div>
    <div className="flex flex-wrap gap-2 border-b border-white/10 p-3"><div className="relative min-w-52 flex-1"><Search className="absolute left-2.5 top-2 h-4 w-4 text-slate-600" /><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Filter current journal" className="w-full border border-white/10 bg-[#060b10] py-1.5 pl-8 pr-3 text-xs outline-none focus:border-cyan-400/50" /></div><button title={paused ? "Resume live refresh" : "Pause live refresh"} onClick={() => setPaused(!paused)} className="border border-white/10 p-2 text-slate-300">{paused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}</button><button title="Refresh now" onClick={() => void refresh()} className="border border-white/10 p-2 text-slate-300">{loading ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}</button><button title="Export visible logs" onClick={save} className="border border-white/10 p-2 text-slate-300"><Download className="h-4 w-4" /></button></div>
    <div className="h-[calc(100vh-19rem)] min-h-96 overflow-auto bg-[#04070b] p-4 font-mono text-xs leading-6">{visible.length ? visible.map((line, index) => <div key={`${index}-${line}`} className={`${/error|failed|fatal/i.test(line) ? "text-rose-300" : /warn/i.test(line) ? "text-amber-300" : "text-slate-400"} border-b border-white/[0.025] hover:bg-white/[0.025]`}>{line}</div>) : <div className="text-slate-600">No matching log lines.</div>}</div>
  </section>;
}
