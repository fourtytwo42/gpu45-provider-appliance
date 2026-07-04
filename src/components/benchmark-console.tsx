"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Activity, Gauge, LoaderCircle, Play, Zap } from "lucide-react";
import { formatBytes, formatDuration, formatNumber } from "@/lib/format";
import type { BenchmarkJob, BenchmarkProgressSample } from "@/lib/benchmarks";
import type { BenchmarkRun, ModelAsset } from "@/lib/types";

type BenchmarkConsoleProps = {
  model: string;
  models: ModelAsset[];
  initialRuns: BenchmarkRun[];
};

type ChartPoint = {
  label: string;
  generation: number;
  prompt: number;
  temp: number | null;
  vram: number | null;
  duration: number;
  model: string;
};

function isPrimaryModel(model: ModelAsset): boolean {
  const normalized = model.name.toLowerCase();
  return !normalized.includes("mmproj") && !/^(mtp|draft)([-_.]|$)/i.test(normalized);
}

function modelId(model: ModelAsset): string {
  return model.servedAlias || model.name;
}

function sampleLabel(sample: BenchmarkProgressSample): string {
  return `${Math.max(0, Math.round(sample.elapsedMs / 1000))}s`;
}

function metricValue(value: number | null | undefined, unit: string, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return `${formatNumber(value, decimals)}${unit ? ` ${unit}` : ""}`;
}

function latestSample(job: BenchmarkJob | null): BenchmarkProgressSample | null {
  return job?.samples.at(-1) ?? null;
}

export function BenchmarkConsole({ model, models, initialRuns }: BenchmarkConsoleProps) {
  const [selectedPath, setSelectedPath] = useState(() => models.find((entry) => entry.active && isPrimaryModel(entry))?.path ?? models.find(isPrimaryModel)?.path ?? "");
  const [job, setJob] = useState<BenchmarkJob | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const selectableModels = useMemo(() => {
    const primary = models.filter(isPrimaryModel);
    return primary.length > 0 ? primary : models;
  }, [models]);

  const selectedModel = selectableModels.find((entry) => entry.path === selectedPath) ?? selectableModels[0] ?? null;
  const currentSample = latestSample(job);
  const progressPercent = job ? Math.min(100, Math.max(3, ((job.partialRuns.length + (job.status === "running" ? 0.5 : 0)) / Math.max(job.totalRuns, 1)) * 100)) : 0;

  const historyData = useMemo<ChartPoint[]>(() => initialRuns.slice(0, 12).reverse().map((run, index) => ({
    label: `#${index + 1}`,
    generation: Number(run.generationTokensPerSecond.toFixed(2)),
    prompt: Number(run.promptTokensPerSecond.toFixed(2)),
    temp: run.peakGpuTempC ?? null,
    vram: run.peakVramBytes ? Number((run.peakVramBytes / 1024 / 1024 / 1024).toFixed(2)) : null,
    duration: Number((run.durationMs / 1000).toFixed(1)),
    model: run.modelName,
  })), [initialRuns]);

  const liveData = useMemo(() => (job?.samples ?? []).slice(-60).map((sample) => ({
    time: sampleLabel(sample),
    temp: sample.gpuTempC,
    gpu: sample.gpuUsage,
    power: sample.gpuPowerW,
    tps: sample.tokensPerSecond,
    vram: sample.vramUsedBytes === null ? null : Number((sample.vramUsedBytes / 1024 / 1024 / 1024).toFixed(2)),
  })), [job?.samples]);

  useEffect(() => {
    if (!job || job.status === "completed" || job.status === "failed") return;
    const timer = window.setInterval(async () => {
      const response = await fetch(`/api/benchmarks?id=${encodeURIComponent(job.id)}`, { cache: "no-store" });
      const payload = await response.json();
      if (response.ok) {
        setJob(payload.job);
        if (payload.job.status === "completed" || payload.job.status === "failed") {
          setRunning(false);
          if (payload.job.status === "completed") window.setTimeout(() => location.reload(), 1200);
        }
      } else {
        setRunning(false);
        setError(payload.error ?? "Unable to read benchmark status");
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job]);

  async function run() {
    if (!selectedModel) return;
    setRunning(true);
    setError("");
    setJob(null);
    const response = await fetch("/api/benchmarks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: modelId(selectedModel),
        modelPath: selectedModel.path,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setRunning(false);
      setError(payload.error ?? "Benchmark failed");
      return;
    }
    setJob(payload.job);
  }

  return (
    <div className="space-y-4">
      <section className="border border-white/10 bg-[#081018] p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold text-white">Benchmark runner</h1>
            <p className="mt-1 text-sm text-slate-500">Fixed two-run throughput and thermal test with 2k max output tokens.</p>
          </div>
          <Gauge className="h-5 w-5 text-cyan-300" />
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(260px,0.8fr)_1.2fr]">
          <div className="space-y-4">
            <label className="block">
              <span className="text-xs text-slate-400">Model</span>
              <select
                value={selectedPath}
                onChange={(event) => setSelectedPath(event.target.value)}
                disabled={running}
                className="mt-1 w-full border border-white/10 bg-[#050a0f] px-3 py-2 font-mono text-xs text-slate-200 outline-none focus:border-cyan-400/50 disabled:opacity-60"
              >
                {selectableModels.map((entry) => (
                  <option key={entry.path} value={entry.path}>
                    {entry.active ? "ACTIVE - " : ""}{entry.servedAlias || entry.name}
                  </option>
                ))}
              </select>
            </label>

            <div className="grid grid-cols-3 gap-2">
              <div className="border border-white/10 bg-[#050a0f] p-3">
                <div className="text-lg font-semibold text-white">2</div>
                <div className="text-[11px] text-slate-500">runs</div>
              </div>
              <div className="border border-white/10 bg-[#050a0f] p-3">
                <div className="text-lg font-semibold text-white">2k</div>
                <div className="text-[11px] text-slate-500">max output</div>
              </div>
              <div className="border border-white/10 bg-[#050a0f] p-3">
                <div className="text-lg font-semibold text-white">0.0</div>
                <div className="text-[11px] text-slate-500">temp</div>
              </div>
            </div>

            {error ? <div className="border border-rose-400/30 bg-rose-400/10 p-2 text-sm text-rose-200">{error}</div> : null}

            <button
              disabled={running || !selectedModel}
              onClick={() => void run()}
              className="flex w-full items-center justify-center gap-2 border border-cyan-400/30 bg-cyan-400/10 py-2.5 text-sm font-medium text-cyan-200 disabled:opacity-50"
            >
              {running ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              {running ? "Benchmark running..." : "Start benchmark"}
            </button>

            <div className="text-xs text-slate-600">
              Current provider model: <span className="font-mono text-slate-400">{model || "unknown"}</span>
            </div>
          </div>

          <div className="border border-white/10 bg-[#050a0f] p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-white">{job?.message ?? "Ready"}</div>
                <div className="mt-1 text-xs text-slate-500">
                  {job ? `Run ${job.activeRun || 1} of ${job.totalRuns}` : "Select a model and start the fixed benchmark."}
                </div>
              </div>
              <Activity className="h-5 w-5 text-emerald-300" />
            </div>
            <div className="mt-4 h-2 border border-white/10 bg-[#0c1520]">
              <div className="h-full bg-cyan-400 transition-all" style={{ width: `${progressPercent}%` }} />
            </div>

            <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              <LiveMetric label="GPU" value={metricValue(currentSample?.gpuUsage, "%", 0)} color="text-blue-300" />
              <LiveMetric label="Temp" value={metricValue(currentSample?.gpuTempC, "C", 1)} color="text-rose-300" />
              <LiveMetric label="Power" value={metricValue(currentSample?.gpuPowerW, "W", 0)} color="text-amber-300" />
              <LiveMetric label="VRAM" value={currentSample?.vramUsedBytes ? formatBytes(currentSample.vramUsedBytes) : "n/a"} color="text-violet-300" />
            </div>

            <div className="mt-4 h-48">
              {liveData.length === 0 ? (
                <div className="flex h-full items-center justify-center border border-dashed border-white/10 text-sm text-slate-600">Live telemetry will appear during the run.</div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={liveData}>
                    <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
                    <XAxis dataKey="time" stroke="#64748b" fontSize={11} />
                    <YAxis stroke="#64748b" fontSize={11} />
                    <Tooltip contentStyle={{ background: "#050a0f", border: "1px solid rgba(255,255,255,0.12)", color: "#e2e8f0" }} />
                    <Line type="monotone" dataKey="temp" name="temp C" stroke="#fb7185" dot={false} strokeWidth={2} />
                    <Line type="monotone" dataKey="gpu" name="gpu %" stroke="#60a5fa" dot={false} strokeWidth={2} />
                    <Line type="monotone" dataKey="tps" name="tok/s" stroke="#34d399" dot={false} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
        <div className="border border-white/10 bg-[#081018] p-4">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-sm font-semibold text-white">History visuals</h2>
              <p className="mt-1 text-xs text-slate-500">Recent SQLite benchmark history by throughput, duration, peak temp, and VRAM.</p>
            </div>
            <Zap className="h-4 w-4 text-amber-300" />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <HistoryChart title="Generation throughput" data={historyData} kind="throughput" />
            <HistoryChart title="Thermal and memory peaks" data={historyData} kind="thermal" />
          </div>
        </div>

        <div className="border border-white/10 bg-[#081018] p-4">
          <h2 className="text-sm font-semibold text-white">SQLite history</h2>
          <div className="mt-4 space-y-3">
            {initialRuns.length === 0 ? (
              <div className="border border-dashed border-white/10 p-8 text-center text-sm text-slate-500">No benchmark runs recorded.</div>
            ) : initialRuns.map((run) => (
              <article key={run.id} className="border border-white/10 bg-[#050a0f] p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate font-mono text-xs text-cyan-200">{run.modelName}</div>
                    <div className="mt-1 text-xs text-slate-500">{run.notes ?? "fixed benchmark"}</div>
                  </div>
                  <time className="text-[11px] text-slate-600">{new Date(run.createdAt).toLocaleString()}</time>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Stat label="gen tok/s" value={formatNumber(run.generationTokensPerSecond, 1)} color="border-emerald-400" />
                  <Stat label="prompt tok/s" value={formatNumber(run.promptTokensPerSecond, 1)} color="border-cyan-400" />
                  <Stat label="duration" value={formatDuration(run.durationMs)} color="border-amber-400" />
                  <Stat label="peak temp" value={run.peakGpuTempC === null || run.peakGpuTempC === undefined ? "n/a" : `${formatNumber(run.peakGpuTempC, 1)} C`} color="border-rose-400" />
                </div>
                <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-slate-600">
                  <span>{run.totalTokens.toLocaleString()} tokens</span>
                  <span>{run.peakVramBytes ? `${formatBytes(run.peakVramBytes)} peak VRAM` : "VRAM n/a"}</span>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function LiveMetric({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="border border-white/10 bg-[#081018] p-3">
      <div className={`text-lg font-semibold ${color}`}>{value}</div>
      <div className="text-[11px] text-slate-500">{label}</div>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className={`border-l-2 ${color} pl-2`}>
      <div className="text-lg font-semibold text-white">{value}</div>
      <div className="text-[11px] text-slate-500">{label}</div>
    </div>
  );
}

function HistoryChart({ title, data, kind }: { title: string; data: ChartPoint[]; kind: "throughput" | "thermal" }) {
  return (
    <div className="border border-white/10 bg-[#050a0f] p-3">
      <div className="text-xs font-medium text-slate-300">{title}</div>
      <div className="mt-3 h-56">
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center border border-dashed border-white/10 text-sm text-slate-600">No chart data yet.</div>
        ) : kind === "throughput" ? (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="label" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} />
              <Tooltip contentStyle={{ background: "#050a0f", border: "1px solid rgba(255,255,255,0.12)", color: "#e2e8f0" }} />
              <Bar dataKey="generation" name="gen tok/s" fill="#34d399" />
              <Bar dataKey="prompt" name="prompt tok/s" fill="#22d3ee" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
              <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
              <XAxis dataKey="label" stroke="#64748b" fontSize={11} />
              <YAxis stroke="#64748b" fontSize={11} />
              <Tooltip contentStyle={{ background: "#050a0f", border: "1px solid rgba(255,255,255,0.12)", color: "#e2e8f0" }} />
              <Area type="monotone" dataKey="temp" name="peak temp C" stroke="#fb7185" fill="#fb718533" />
              <Area type="monotone" dataKey="vram" name="peak VRAM GB" stroke="#a78bfa" fill="#a78bfa33" />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
