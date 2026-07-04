"use client";

import { useEffect, useState } from "react";
import { Activity, Copy, Cpu, Database, Fan, Gauge, HardDrive, KeyRound, Server, Thermometer, Zap } from "lucide-react";
import { OperationalChart } from "./operational-chart";
import { InstrumentGauge } from "./instrument-gauge";
import { StatusPill } from "./status-pill";
import { formatBytes, formatNumber, formatPercent } from "@/lib/format";
import type { DashboardSnapshot, LiveTelemetry, MetricSeries } from "@/lib/types";

const MAX_POINTS = 180;

function append(series: MetricSeries, timestamp: string, value: number | null): MetricSeries {
  if (value === null || !Number.isFinite(value)) return series;
  return { ...series, points: [...series.points, { timestamp, value }].slice(-MAX_POINTS) };
}

function updateCharts(charts: DashboardSnapshot["charts"], live: LiveTelemetry): DashboardSnapshot["charts"] {
  const s = live.system;
  const gib = 1024 ** 3;
  return {
    ...charts,
    gpuTempEdge: append(charts.gpuTempEdge, live.collectedAt, s.gpuTempEdgeC),
    gpuTempJunction: append(charts.gpuTempJunction, live.collectedAt, s.gpuTempJunctionC),
    gpuTempMemory: append(charts.gpuTempMemory, live.collectedAt, s.gpuTempMemoryC),
    gpuPower: append(charts.gpuPower, live.collectedAt, s.gpuPowerW),
    gpuUsage: append(charts.gpuUsage, live.collectedAt, s.gpuUsage),
    vramUsed: append(charts.vramUsed, live.collectedAt, s.vramUsedBytes === null ? null : s.vramUsedBytes / gib),
    vramTotal: append(charts.vramTotal, live.collectedAt, s.vramTotalBytes === null ? null : s.vramTotalBytes / gib),
    vramFree: append(charts.vramFree, live.collectedAt, s.vramUsedBytes === null || s.vramTotalBytes === null ? null : (s.vramTotalBytes - s.vramUsedBytes) / gib),
    cpuUsage: append(charts.cpuUsage, live.collectedAt, s.cpuUsage),
    ramUsage: append(charts.ramUsage, live.collectedAt, s.ramUsedBytes / gib),
    diskUsed: append(charts.diskUsed, live.collectedAt, s.diskUsedBytes / gib),
    diskFree: append(charts.diskFree, live.collectedAt, s.diskFreeBytes / gib),
    fanPwm: append(charts.fanPwm, live.collectedAt, s.fanPwm),
    fanRpm: append(charts.fanRpm, live.collectedAt, s.fanRpm),
    tokensPerSecond: append(charts.tokensPerSecond, live.collectedAt, live.provider.tokensPerSecond),
  };
}

function Capacity({ label, used, total, color }: { label: string; used: number; total: number; color: string }) {
  const percent = total > 0 ? Math.min(100, used / total * 100) : 0;
  return <div><div className="mb-1.5 flex justify-between text-xs"><span className="text-slate-400">{label}</span><span className="font-mono text-slate-300">{formatPercent(percent, 0)}</span></div><div className="h-1.5 bg-white/10"><div className="h-full" style={{ width: `${percent}%`, background: color }} /></div><div className="mt-1 text-[11px] text-slate-600">{formatBytes(used)} of {formatBytes(total)}</div></div>;
}

export function LiveOverview({ initial, endpoint }: { initial: DashboardSnapshot; endpoint: { allowAnonymous: boolean; visibleModels: number; endpointBase: string } }) {
  const [live, setLive] = useState<LiveTelemetry>({ collectedAt: initial.collectedAt, provider: initial.provider, system: initial.system });
  const [charts, setCharts] = useState(initial.charts);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    const source = new EventSource("/api/live");
    source.addEventListener("telemetry", (event) => {
      const next = JSON.parse((event as MessageEvent).data) as LiveTelemetry;
      setLive(next); setCharts((current) => updateCharts(current, next)); setConnected(true);
    });
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, []);
  const s = live.system;
  const vramFree = s.vramTotalBytes !== null && s.vramUsedBytes !== null ? s.vramTotalBytes - s.vramUsedBytes : null;
  const vramPercent = s.vramUsedBytes !== null && s.vramTotalBytes ? (s.vramUsedBytes / s.vramTotalBytes) * 100 : null;
  return <div className="space-y-4">
    <section className="flex flex-wrap items-center justify-between gap-4 border border-white/10 bg-[#0a1119] px-4 py-3">
      <div className="min-w-0"><div className="flex items-center gap-2"><StatusPill status={live.provider.status}>{live.provider.status}</StatusPill><span className="truncate font-mono text-sm text-white">{live.provider.model}</span></div><div className="mt-1 text-xs text-slate-500">{live.provider.providerUrl}</div></div>
      <div className="flex items-center gap-2 text-xs"><span className={`h-2 w-2 ${connected ? "bg-emerald-400" : "bg-rose-400"}`} /><span className="text-slate-400">{connected ? "Live stream" : "Reconnecting"}</span><span className="font-mono text-slate-600">{new Date(live.collectedAt).toLocaleTimeString()}</span></div>
    </section>
    <section className="grid gap-4 border border-white/10 bg-[#0a1119] p-4 lg:grid-cols-[1.4fr_.8fr_.8fr] lg:items-center">
      <div className="min-w-0"><div className="flex items-center gap-2 text-xs uppercase text-slate-500"><Server className="h-3.5 w-3.5 text-cyan-300" />OpenAI-compatible endpoint</div><div className="mt-2 flex items-center gap-2"><code className="min-w-0 flex-1 truncate border border-white/10 bg-[#05090e] px-3 py-2 text-sm text-cyan-100">{endpoint.endpointBase}/v1</code><button title="Copy endpoint URL" onClick={() => void navigator.clipboard.writeText(`${endpoint.endpointBase}/v1`)} className="border border-white/10 p-2.5 text-slate-300 hover:border-cyan-400/30 hover:text-cyan-200"><Copy className="h-4 w-4" /></button></div><div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-slate-600"><span>POST /v1/responses</span><span>GET /v1/models</span></div></div>
      <div className="border-l border-white/10 pl-4"><div className="flex items-center gap-2 text-xs text-slate-500"><KeyRound className="h-3.5 w-3.5 text-amber-300" />Authentication</div><div className="mt-2 text-sm font-medium text-white">{endpoint.allowAnonymous ? "Optional API key" : "API key required"}</div><div className="mt-1 text-xs text-slate-600">Bearer token via Authorization header</div></div>
      <div className="border-l border-white/10 pl-4"><div className="flex items-center gap-2 text-xs text-slate-500"><Database className="h-3.5 w-3.5 text-violet-300" />Model catalog</div><div className="mt-2 text-sm font-medium text-white">{endpoint.visibleModels} visible model{endpoint.visibleModels === 1 ? "" : "s"}</div><div className="mt-1 text-xs text-slate-600">Unsupported names fall back automatically</div></div>
    </section>
    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
      <InstrumentGauge label="Junction temp" value={s.gpuTempJunctionC} max={110} displayValue={s.gpuTempJunctionC === null ? "n/a" : `${formatNumber(s.gpuTempJunctionC, 1)} C`} detail={`edge ${formatNumber(s.gpuTempEdgeC, 1)} C`} icon={Thermometer} color="#fb7185" />
      <InstrumentGauge label="GPU busy" value={s.gpuUsage} max={100} displayValue={s.gpuUsage === null ? "n/a" : formatPercent(s.gpuUsage, 0)} detail={`${live.provider.activeRequests} active request(s)`} icon={Activity} color="#38bdf8" />
      <InstrumentGauge label="Throughput" value={live.provider.tokensPerSecond} max={50} displayValue={`${formatNumber(live.provider.tokensPerSecond, 1)} tok/s`} detail={`${live.provider.completionTokens.toLocaleString()} generated`} icon={Gauge} color="#34d399" />
      <InstrumentGauge label="VRAM used" value={vramPercent} max={100} displayValue={s.vramUsedBytes === null ? "n/a" : formatBytes(s.vramUsedBytes)} detail={vramFree === null ? "sensor unavailable" : `${formatBytes(vramFree)} free`} icon={Database} color="#a78bfa" />
      <InstrumentGauge label="GPU power" value={s.gpuPowerW} max={225} displayValue={s.gpuPowerW === null ? "n/a" : `${formatNumber(s.gpuPowerW, 0)} W`} detail="board power" icon={Zap} color="#fbbf24" />
      <InstrumentGauge label="Fan speed" value={s.fanRpm} max={16000} displayValue={s.fanRpm === null ? "n/a" : `${Math.round(s.fanRpm).toLocaleString()} RPM`} detail={`PWM ${s.fanPwm ?? "n/a"}`} icon={Fan} color="#22d3ee" />
    </section>
    <section className="grid gap-4 xl:grid-cols-2">
      <OperationalChart title="Thermal envelope" subtitle="Edge, junction, and memory sensors" series={[charts.gpuTempEdge, charts.gpuTempJunction, charts.gpuTempMemory]} />
      <OperationalChart title="Inference activity" subtitle="Accelerator utilization and current generation rate" series={[charts.gpuUsage, charts.tokensPerSecond]} />
      <OperationalChart title="Memory pressure" subtitle="VRAM allocation and system RAM" series={[charts.vramUsed, charts.vramFree, charts.ramUsage]} />
      <OperationalChart title="Power and cooling" subtitle="Board power, fan command, and measured speed" series={[charts.gpuPower, charts.fanPwm, charts.fanRpm]} />
    </section>
    <section className="grid gap-4 border border-white/10 bg-[#0a1119] p-4 lg:grid-cols-[1fr_1fr_1.2fr]">
      <Capacity label="Model storage" used={s.diskUsedBytes} total={s.diskTotalBytes} color="#22d3ee" />
      <Capacity label="System RAM" used={s.ramUsedBytes} total={s.ramTotalBytes} color="#a78bfa" />
      <div className="grid grid-cols-3 gap-3 text-center"><div><Cpu className="mx-auto h-4 w-4 text-amber-300" /><div className="mt-1 font-mono text-sm">{formatPercent(s.cpuUsage, 0)}</div><div className="text-[11px] text-slate-600">CPU</div></div><div><Fan className="mx-auto h-4 w-4 text-cyan-300" /><div className="mt-1 font-mono text-sm">{s.fanPwm === null ? "n/a" : Math.round(s.fanPwm)}</div><div className="text-[11px] text-slate-600">fan PWM</div></div><div><HardDrive className="mx-auto h-4 w-4 text-emerald-300" /><div className="mt-1 font-mono text-sm">{formatBytes(s.diskFreeBytes)}</div><div className="text-[11px] text-slate-600">free</div></div></div>
    </section>
  </div>;
}
