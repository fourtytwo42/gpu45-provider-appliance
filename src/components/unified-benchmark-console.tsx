"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, CircleAlert, Gauge, LoaderCircle, Play, RefreshCw } from "lucide-react";
import type { AgenticCampaignDetail, AgenticLatestResult, AgenticModel } from "@/lib/agentic-benchmarks";
import type { BenchmarkJob } from "@/lib/benchmarks";
import {
  buildUnifiedBenchmarkRows,
  COMMON_AGENTIC_SUITES,
  COMMON_AGENTIC_SUITE_IDS,
  COMMON_AGENTIC_TASKS,
} from "@/lib/benchmark-results";
import { formatBytes, formatDuration, formatNumber } from "@/lib/format";
import type { BenchmarkRun } from "@/lib/types";

type Props = {
  initialRuns: BenchmarkRun[];
  agenticModels: AgenticModel[];
  agenticResults: AgenticLatestResult[];
};

type RunStage = "idle" | "throughput" | "agentic" | "complete" | "failed";

type RunState = {
  stage: RunStage;
  modelName: string;
  message: string;
  progress: number;
  throughputJobId?: string;
  campaignId?: string;
};

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const terminalAgenticStatuses = new Set(["completed", "failed", "cancelled"]);

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "Not tested";
  return `${(value * 100).toFixed(1)}%`;
}

function suiteScore(result: AgenticLatestResult | null, suiteId: string): string {
  const suite = result?.suites[suiteId];
  if (!suite) return "Not tested";
  if (suite.score === null) return `${suite.completedTasks}/${suite.expectedTasks}`;
  return percent(suite.score);
}

function dateLabel(value: string | null): string {
  if (!value) return "Never";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Chicago",
  }).format(parsed);
}

function statusTone(status: string): string {
  if (status === "completed" || status === "eligible") return "border-emerald-400/25 bg-emerald-400/10 text-emerald-300";
  if (["running", "queued", "loading-model"].includes(status)) return "border-cyan-400/25 bg-cyan-400/10 text-cyan-300";
  if (status === "paused" || status === "pending") return "border-amber-400/25 bg-amber-400/10 text-amber-300";
  return "border-rose-400/25 bg-rose-400/10 text-rose-300";
}

function statusLabel(status: string | undefined): string {
  if (!status) return "Not tested";
  return status.replaceAll("-", " ");
}

function missingThroughputLabel(result: AgenticLatestResult | null): string {
  return result?.systemType === "agent-system-reference" ? "Cloud n/a" : "Not tested";
}

async function responseJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(String((payload as { error?: string }).error || `Request failed with HTTP ${response.status}`));
  }
  return payload as T;
}

export function UnifiedBenchmarkConsole({ initialRuns, agenticModels, agenticResults }: Props) {
  const router = useRouter();
  const [selectedName, setSelectedName] = useState(agenticModels[0]?.name || "");
  const [run, setRun] = useState<RunState>({ stage: "idle", modelName: "", message: "", progress: 0 });
  const [error, setError] = useState("");
  const rows = useMemo(
    () => buildUnifiedBenchmarkRows(agenticModels, initialRuns, agenticResults),
    [agenticModels, agenticResults, initialRuns],
  );
  const selectedModel = agenticModels.find((model) => model.name === selectedName) || null;
  const running = run.stage === "throughput" || run.stage === "agentic";

  async function runFullBenchmark() {
    if (!selectedModel) return;
    setError("");
    setRun({
      stage: "throughput",
      modelName: selectedModel.name,
      message: "Loading the model and starting two fixed throughput passes",
      progress: 2,
    });
    try {
      const started = await responseJson<{ job: BenchmarkJob }>(await fetch("/api/benchmarks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: selectedModel.name,
          modelPath: selectedModel.modelPath,
          repetitions: 2,
          maxOutputTokens: 2048,
          temperature: 0,
          warmup: false,
        }),
      }));
      let throughput = started.job;
      setRun((current) => ({ ...current, throughputJobId: throughput.id }));
      while (!["completed", "failed"].includes(throughput.status)) {
        await delay(2500);
        throughput = (await responseJson<{ job: BenchmarkJob }>(
          await fetch(`/api/benchmarks?id=${encodeURIComponent(throughput.id)}`, { cache: "no-store" }),
        )).job;
        const completed = throughput.partialRuns.length;
        const phaseProgress = Math.min(100, Math.round((completed / Math.max(throughput.totalRuns, 1)) * 100));
        setRun((current) => ({
          ...current,
          message: throughput.message,
          progress: Math.max(3, Math.round(phaseProgress * 0.15)),
        }));
      }
      if (throughput.status === "failed") throw new Error(throughput.error || "Throughput test failed");

      setRun((current) => ({
        ...current,
        stage: "agentic",
        message: `Throughput complete. Queuing ${COMMON_AGENTIC_TASKS} agentic tasks`,
        progress: 15,
      }));
      const created = await responseJson<{ id: string }>(await fetch("/api/agentic-benchmarks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `Unified benchmark: ${selectedModel.name}`,
          preset: "common",
          profileNames: [selectedModel.name],
          suiteIds: COMMON_AGENTIC_SUITE_IDS,
        }),
      }));
      let detail: AgenticCampaignDetail;
      do {
        await delay(3000);
        detail = await responseJson<AgenticCampaignDetail>(
          await fetch(`/api/agentic-benchmarks/${encodeURIComponent(created.id)}`, { cache: "no-store" }),
        );
        const completed = detail.runs.reduce((total, item) => total + Number(item.completed_tasks || 0), 0);
        const expected = detail.runs.reduce((total, item) => total + Number(item.expected_tasks || 0), 0);
        const phaseProgress = expected > 0 ? completed / expected : 0;
        setRun((current) => ({
          ...current,
          campaignId: created.id,
          message: `${statusLabel(detail.campaign.status)}: ${completed} of ${expected || COMMON_AGENTIC_TASKS} agentic tasks complete`,
          progress: Math.min(99, 15 + Math.round(phaseProgress * 85)),
        }));
      } while (!terminalAgenticStatuses.has(detail.campaign.status));
      if (detail.campaign.status !== "completed") {
        throw new Error(detail.campaign.error || `Agentic test ${detail.campaign.status}`);
      }
      setRun((current) => ({
        ...current,
        stage: "complete",
        message: "Full benchmark complete. The comparison table is updating.",
        progress: 100,
      }));
      router.refresh();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Benchmark failed";
      setError(message);
      setRun((current) => ({ ...current, stage: "failed", message }));
    }
  }

  return (
    <section className="appliance-panel overflow-hidden rounded-xl">
      <div className="border-b border-white/8 px-5 py-5 sm:px-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
              <Gauge className="h-4 w-4" />
              Unified model benchmark
            </div>
            <h1 className="text-2xl font-semibold text-white">One table, one test recipe, every model</h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              Each row combines the latest capability scores and throughput measurements for that model.
              Reruns always use the same two throughput passes and the same {COMMON_AGENTIC_TASKS} agentic tasks.
            </p>
          </div>
          <button
            type="button"
            onClick={() => router.refresh()}
            disabled={running}
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-white/10 bg-white/5 px-3 text-sm font-medium text-slate-300 transition hover:border-white/20 hover:text-white"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh results
          </button>
        </div>

        <div className="mt-5 grid gap-3 rounded-lg border border-cyan-400/15 bg-cyan-400/[0.04] p-4 lg:grid-cols-[minmax(16rem,1fr)_auto_auto] lg:items-end">
          <label className="block">
            <span className="mb-2 block text-xs font-semibold uppercase tracking-wider text-slate-400">Model to test</span>
            <select
              value={selectedName}
              onChange={(event) => setSelectedName(event.target.value)}
              disabled={running || agenticModels.length === 0}
              className="input-control w-full"
            >
              {agenticModels.length === 0 ? <option value="">No model profiles found</option> : null}
              {agenticModels.map((model) => (
                <option key={model.name} value={model.name}>
                  {model.description || model.servedAlias || model.name}
                </option>
              ))}
            </select>
          </label>
          <div className="text-xs leading-5 text-slate-400">
            <div className="font-semibold text-slate-200">Fixed comparison recipe</div>
            <div>2 throughput passes + {COMMON_AGENTIC_TASKS} agentic tasks</div>
          </div>
          <button
            type="button"
            onClick={runFullBenchmark}
            disabled={running || !selectedModel}
            className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-cyan-400 px-5 text-sm font-semibold text-slate-950 transition hover:bg-cyan-300"
          >
            {running ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 fill-current" />}
            {running ? "Benchmark running" : "Run full benchmark"}
          </button>
        </div>

        {run.stage !== "idle" ? (
          <div className={`mt-3 rounded-lg border p-4 ${run.stage === "failed" ? "border-rose-400/25 bg-rose-400/[0.05]" : "border-white/10 bg-black/20"}`}>
            <div className="flex items-center justify-between gap-4 text-sm">
              <div className="flex min-w-0 items-center gap-2">
                {run.stage === "complete" ? <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-300" /> : null}
                {run.stage === "failed" ? <CircleAlert className="h-4 w-4 shrink-0 text-rose-300" /> : null}
                {running ? <LoaderCircle className="h-4 w-4 shrink-0 animate-spin text-cyan-300" /> : null}
                <span className="truncate font-medium text-slate-200">{run.modelName}: {run.message}</span>
              </div>
              <span className="shrink-0 font-mono text-xs text-slate-400">{run.progress}%</span>
            </div>
            <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-white/8">
              <div className={`h-full rounded-full transition-all duration-500 ${run.stage === "failed" ? "bg-rose-400" : "bg-cyan-400"}`} style={{ width: `${run.progress}%` }} />
            </div>
          </div>
        ) : null}
        {error ? <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p> : null}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[1380px] border-collapse text-left text-sm">
          <thead className="bg-black/25">
            <tr className="border-b border-white/8 text-[11px] uppercase tracking-wider text-slate-500">
              <th rowSpan={2} className="sticky left-0 z-20 w-[260px] bg-[#0a0e15] px-5 py-3">Model</th>
              <th rowSpan={2} className="px-3 py-3">Latest result</th>
              <th colSpan={7} className="border-l border-white/8 px-3 py-2 text-center text-violet-300">Agentic capability</th>
              <th colSpan={5} className="border-l border-white/8 px-3 py-2 text-center text-cyan-300">Throughput and hardware</th>
            </tr>
            <tr className="border-b border-white/10 text-xs text-slate-400">
              <th className="border-l border-white/8 px-3 py-3">Composite</th>
              {COMMON_AGENTIC_SUITES.map((suite) => <th key={suite.id} className="px-3 py-3">{suite.label}</th>)}
              <th className="px-3 py-3">Tasks</th>
              <th className="px-3 py-3">Invalid</th>
              <th className="border-l border-white/8 px-3 py-3">Prompt tok/s</th>
              <th className="px-3 py-3">Output tok/s</th>
              <th className="px-3 py-3">Duration</th>
              <th className="px-3 py-3">Peak GPU</th>
              <th className="px-3 py-3">Peak VRAM</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const agenticStatus = row.agentic?.status;
              return (
                <tr key={row.key} className="border-b border-white/[0.06] text-slate-300 transition hover:bg-white/[0.025]">
                  <td className="sticky left-0 z-10 bg-[#0b1018] px-5 py-4">
                    <div className="font-semibold text-white">{row.displayName}</div>
                    <div className="mt-1 font-mono text-[11px] text-slate-500">{row.profileName}</div>
                    {row.agentic?.systemType === "agent-system-reference" ? (
                      <div className="mt-1 text-[10px] font-semibold uppercase tracking-wider text-violet-300">
                        Agent-system reference
                      </div>
                    ) : null}
                  </td>
                  <td className="px-3 py-4">
                    <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold uppercase tracking-wide ${agenticStatus ? statusTone(agenticStatus) : "border-white/10 bg-white/5 text-slate-500"}`}>
                      {statusLabel(agenticStatus)}
                    </span>
                    <div className="mt-2 whitespace-nowrap text-xs text-slate-500">{dateLabel(row.latestAt)}</div>
                  </td>
                  <td className="border-l border-white/[0.06] px-3 py-4 font-mono font-semibold text-violet-200">{percent(row.agentic?.compositeScore)}</td>
                  {COMMON_AGENTIC_SUITES.map((suite) => (
                    <td key={suite.id} className="px-3 py-4 font-mono text-xs">{suiteScore(row.agentic, suite.id)}</td>
                  ))}
                  <td className="px-3 py-4 font-mono text-xs">
                    {row.agentic ? `${row.agentic.passedTasks} pass / ${row.agentic.failedTasks} fail` : "Not tested"}
                  </td>
                  <td className="px-3 py-4 font-mono text-xs">{row.agentic ? percent(row.agentic.invalidOutputRate) : "Not tested"}</td>
                  <td className="border-l border-white/[0.06] px-3 py-4 font-mono text-cyan-200">
                    {row.throughput ? formatNumber(row.throughput.promptTokensPerSecond, 1) : missingThroughputLabel(row.agentic)}
                  </td>
                  <td className="px-3 py-4 font-mono font-semibold text-cyan-200">
                    {row.throughput ? formatNumber(row.throughput.generationTokensPerSecond, 1) : missingThroughputLabel(row.agentic)}
                  </td>
                  <td className="px-3 py-4 font-mono text-xs">{row.throughput ? formatDuration(row.throughput.durationMs) : missingThroughputLabel(row.agentic)}</td>
                  <td className="px-3 py-4 font-mono text-xs">
                    {row.throughput?.peakGpuTempC == null ? missingThroughputLabel(row.agentic) : `${formatNumber(row.throughput.peakGpuTempC, 1)} C`}
                  </td>
                  <td className="px-3 py-4 font-mono text-xs">{row.throughput ? formatBytes(row.throughput.peakVramBytes) : missingThroughputLabel(row.agentic)}</td>
                </tr>
              );
            })}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={14} className="px-6 py-14 text-center text-slate-500">
                  No model profiles or benchmark history are available yet.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <div className="border-t border-white/8 px-5 py-3 text-xs text-slate-500">
        Agentic composite weights: SWE 35%, Terminal 30%, BFCL 20%, Tau 15%. Local models use the 67-task common suite.
        Agent-system references use their saved 11-task reference panel and do not report local GPU throughput or hardware metrics.
      </div>
    </section>
  );
}
