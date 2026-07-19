"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, Gauge, LoaderCircle, RefreshCw, Rocket, Scale, X, Zap } from "lucide-react";
import type {
  AgenticCampaignDetail,
  AgenticEfficiencyReport,
  AgenticModel,
  AgenticSuite,
} from "@/lib/agentic-benchmarks";
import {
  buildAgenticLeaderboard,
  type AgenticRankingSummary,
  type AgenticRunSummary,
} from "@/lib/agentic-leaderboard";

type Props = {
  detail: AgenticCampaignDetail;
  models: AgenticModel[];
  suiteById: Map<string, AgenticSuite>;
  busy: boolean;
  onAction: (action: string) => Promise<void>;
  onClose: () => void;
};

const commonSuites = ["bfcl-v4-local", "tau-text-base", "swe-verified-mini50", "terminal-bench-2"];

function percent(value?: number | null) {
  return value == null ? "-" : `${(value * 100).toFixed(1)}%`;
}

function duration(milliseconds?: number | null) {
  if (!milliseconds) return "-";
  const seconds = milliseconds / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${(seconds / 60).toFixed(1)}m`;
}

function compactNumber(value?: number | null) {
  if (value == null) return "-";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function modelLabel(models: AgenticModel[], profileName: string) {
  return models.find((model) => model.name === profileName)?.description || profileName;
}

function statusClass(status?: string) {
  if (status === "completed") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";
  if (status === "failed") return "border-rose-400/30 bg-rose-400/10 text-rose-300";
  if (status === "running") return "border-cyan-400/30 bg-cyan-400/10 text-cyan-300";
  return "border-amber-400/30 bg-amber-400/10 text-amber-300";
}

export function AgenticCampaignPanel({ detail, models, suiteById, busy, onAction, onClose }: Props) {
  const [view, setView] = useState<"capability" | "efficiency" | "compare">("capability");
  const [efficiency, setEfficiency] = useState<AgenticEfficiencyReport | null>(null);
  const [efficiencyError, setEfficiencyError] = useState<string | null>(null);
  const isCommon = detail.campaign.preset === "common";
  const leaderboard = useMemo(() => buildAgenticLeaderboard(
    detail.runs as unknown as AgenticRunSummary[],
    detail.ranking as unknown as AgenticRankingSummary[],
  ), [detail]);

  const refreshEfficiency = useCallback(async () => {
    if (!isCommon) return;
    try {
      const response = await fetch(`/api/agentic-benchmarks/${detail.campaign.id}/efficiency`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Efficiency results unavailable");
      setEfficiency(payload);
      setEfficiencyError(null);
    } catch (error) {
      setEfficiencyError(error instanceof Error ? error.message : "Efficiency results unavailable");
    }
  }, [detail.campaign.id, isCommon]);

  useEffect(() => {
    if (!isCommon) return;
    const initial = window.setTimeout(() => void refreshEfficiency(), 0);
    const timer = window.setInterval(() => void refreshEfficiency(), 5000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [isCommon, refreshEfficiency]);

  async function act(action: string) {
    await onAction(action);
    await refreshEfficiency();
  }

  return <section className="bg-[#0d131c] p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 className="font-semibold text-white">{detail.campaign.name}</h2>
        <p className="mt-1 text-sm text-slate-500">
          Capability determines whether a model solves the work. Efficiency compares the resource cost of verified solves.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        {(["json", "csv", "markdown"] as const).map((format) => <a
          key={format}
          title={`Export ${format}`}
          href={`/api/agentic-benchmarks/${detail.campaign.id}/export?format=${format}`}
          className="inline-flex h-9 items-center gap-1 px-2 text-xs uppercase text-slate-300 hover:bg-white/5"
        >
          <Download className="h-3.5 w-3.5" />{format}
        </a>)}
        <button type="button" title="Close results" onClick={onClose} className="grid h-9 w-9 place-items-center text-slate-400 hover:bg-white/5 hover:text-white">
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>

    {isCommon && <div className="mt-5 flex border-b border-white/10" role="tablist" aria-label="Benchmark result views">
      {([
        ["capability", "Capability", Gauge],
        ["efficiency", "Efficiency", Zap],
        ["compare", "Compare", Scale],
      ] as const).map(([id, label, Icon]) => <button
        key={id}
        type="button"
        role="tab"
        aria-selected={view === id}
        onClick={() => setView(id)}
        className={`inline-flex h-11 items-center gap-2 border-b-2 px-4 text-sm ${view === id ? "border-cyan-400 text-white" : "border-transparent text-slate-500 hover:text-slate-200"}`}
      >
        <Icon className="h-4 w-4" />{label}
      </button>)}
    </div>}

    {(!isCommon || view === "capability") && <CapabilityTable
      detail={detail}
      models={models}
      suiteById={suiteById}
      leaderboard={leaderboard}
    />}

    {isCommon && view === "efficiency" && <EfficiencyPanel
      report={efficiency}
      error={efficiencyError}
      models={models}
      sourceStatus={detail.campaign.status}
      busy={busy}
      onAction={act}
    />}

    {isCommon && view === "compare" && <ComparePanel
      leaderboard={leaderboard}
      report={efficiency}
      models={models}
    />}

    {detail.artifacts?.length > 0 && <div className="mt-6">
      <h3 className="text-sm font-medium text-white">Recent artifacts</h3>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        {detail.artifacts.slice(0, 12).map((artifact) => <a
          key={artifact.id}
          href={`/api/agentic-benchmarks/${detail.campaign.id}/artifacts/${artifact.id}`}
          className="flex items-center justify-between bg-[#121a26] px-3 py-2 text-xs text-slate-300 hover:text-cyan-200"
        >
          <span className="truncate">{artifact.kind}: {artifact.relative_path.split("/").at(-1)}</span>
          <span className="ml-3 font-mono text-slate-500">{Math.ceil(artifact.size_bytes / 1024)} KB</span>
        </a>)}
      </div>
    </div>}
  </section>;
}

function CapabilityTable({ detail, models, suiteById, leaderboard }: {
  detail: AgenticCampaignDetail;
  models: AgenticModel[];
  suiteById: Map<string, AgenticSuite>;
  leaderboard: ReturnType<typeof buildAgenticLeaderboard>;
}) {
  if (detail.campaign.preset !== "common") {
    return <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {detail.runs.map((run) => <div key={String(run.id)} className="bg-[#121a26] p-3">
        <div className="truncate text-sm text-slate-100">{modelLabel(models, String(run.profile_name))}</div>
        <div className="mt-1 text-xs text-slate-500">{String(run.suite_id)}</div>
        <div className="mt-3 flex items-center justify-between">
          <span className={`border px-2 py-1 text-[10px] uppercase ${statusClass(String(run.status))}`}>{String(run.status)}</span>
          <span className="font-mono text-sm text-white">{run.score == null ? "-" : `${(Number(run.score) * 100).toFixed(1)}%`}</span>
        </div>
      </div>)}
    </div>;
  }
  return <div className="mt-4 overflow-x-auto border-y border-white/8">
    <table className="w-full min-w-[1120px] border-collapse text-left text-sm">
      <thead className="bg-[#121a26] text-[11px] uppercase text-slate-500">
        <tr>
          <th className="px-3 py-3">Rank</th><th className="px-3 py-3">Model</th><th className="px-3 py-3">Progress</th>
          {commonSuites.map((suiteId) => <th key={suiteId} className="px-3 py-3">{suiteById.get(suiteId)?.name || suiteId}</th>)}
          <th className="px-3 py-3">Pass / fail</th><th className="px-3 py-3">Invalid</th><th className="px-3 py-3 text-right">Composite</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-white/8">{leaderboard.map((row) => <tr key={row.profileName} className="hover:bg-white/[0.025]">
        <td className="px-3 py-3 font-mono text-slate-400">{row.rank == null ? "-" : `#${row.rank}`}</td>
        <td className="max-w-64 px-3 py-3"><span className="block truncate font-medium text-slate-100" title={row.profileName}>{modelLabel(models, row.profileName)}</span><span className="mt-1 block truncate font-mono text-[10px] text-slate-600">{row.profileName}</span></td>
        <td className="px-3 py-3"><div className="font-mono text-xs text-slate-200">{row.completedTasks.toLocaleString()} / {row.expectedTasks.toLocaleString()}</div><div className="mt-2 h-1.5 w-28 overflow-hidden bg-white/8"><div className="h-full bg-cyan-400" style={{ width: `${row.expectedTasks ? Math.min(100, row.completedTasks / row.expectedTasks * 100) : 0}%` }} /></div></td>
        {commonSuites.map((suiteId) => { const run = row.suites[suiteId]; return <td key={suiteId} className="px-3 py-3"><div className="font-mono text-sm text-white">{percent(run?.score)}</div><div className="mt-1 text-[10px] text-slate-500">{run ? `${Number(run.completed_tasks || 0).toLocaleString()}/${Number(row.suiteExpectedTasks[suiteId] || 0).toLocaleString()} | ${run.status}` : "not scheduled"}</div></td>; })}
        <td className="px-3 py-3 font-mono text-xs"><span className="text-emerald-300">{row.passedTasks.toLocaleString()}</span><span className="px-1 text-slate-600">/</span><span className="text-rose-300">{row.failedTasks.toLocaleString()}</span></td>
        <td className="px-3 py-3 font-mono text-xs text-slate-300">{percent(row.invalidOutputRate)}</td>
        <td className="px-3 py-3 text-right font-mono text-base font-semibold text-white">{percent(row.compositeScore)}</td>
      </tr>)}</tbody>
    </table>
  </div>;
}

function EfficiencyPanel({ report, error, models, sourceStatus, busy, onAction }: {
  report: AgenticEfficiencyReport | null;
  error: string | null;
  models: AgenticModel[];
  sourceStatus: string;
  busy: boolean;
  onAction: (action: string) => Promise<void>;
}) {
  if (error) return <div className="mt-5 border border-rose-400/30 bg-rose-400/10 p-4 text-sm text-rose-200">{error}</div>;
  if (!report) return <div className="mt-5 flex items-center gap-2 text-sm text-slate-400"><LoaderCircle className="h-4 w-4 animate-spin" />Loading efficiency state</div>;
  if (!report.campaignId) return <div className="mt-5 space-y-4">
    <ReferenceBaseline report={report} busy={busy} onAction={onAction} />
    <div className="bg-[#121a26] p-5">
      <h3 className="font-medium text-white">Finalist panel has not started</h3>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">The three capability leaders will run the same 11 difficult tasks. Failed tasks still consume resources, and only verified solves contribute to efficiency.</p>
      <button type="button" disabled={busy || sourceStatus !== "completed"} onClick={() => void onAction("efficiency")} className="mt-4 inline-flex h-10 items-center gap-2 bg-cyan-400 px-4 text-sm font-semibold text-[#071018] disabled:opacity-40"><Zap className="h-4 w-4" />Run finalist panel</button>
      {sourceStatus !== "completed" && <p className="mt-2 text-xs text-amber-300">Capability testing must finish first.</p>}
    </div>
  </div>;

  return <div className="mt-5 space-y-4">
    <ReferenceBaseline report={report} busy={busy} onAction={onAction} />
    <div className="flex flex-wrap items-center justify-between gap-3 bg-[#121a26] p-4">
      <div><div className="text-xs uppercase text-slate-500">Panel status</div><div className="mt-1 flex items-center gap-2"><span className={`border px-2 py-1 text-[10px] uppercase ${statusClass(report.status)}`}>{report.status}</span><span className="text-sm text-slate-300">{report.rows.reduce((total, row) => total + row.completedTasks, 0)} / {report.rows.reduce((total, row) => total + row.expectedTasks, 0)} tasks</span></div></div>
      <div className="flex gap-2">
        {report.confirmationRecommended && report.status === "completed" && <button type="button" disabled={busy} onClick={() => void onAction("confirm-efficiency")} className="inline-flex h-9 items-center gap-2 border border-amber-400/30 px-3 text-sm text-amber-200"><RefreshCw className="h-4 w-4" />Confirm close result</button>}
        {report.status === "completed" && <button type="button" disabled={busy} onClick={() => void onAction("promote")} className="inline-flex h-9 items-center gap-2 border border-cyan-400/30 px-3 text-sm text-cyan-200"><Rocket className="h-4 w-4" />Deep qualification</button>}
      </div>
    </div>
    <div className="overflow-x-auto border-y border-white/8">
      <table className="w-full min-w-[1180px] text-left text-sm">
        <thead className="bg-[#121a26] text-[11px] uppercase text-slate-500"><tr><th className="px-3 py-3">Rank</th><th className="px-3 py-3">Model</th><th className="px-3 py-3">Capability</th><th className="px-3 py-3">11-task score</th><th className="px-3 py-3">Verified solves</th><th className="px-3 py-3">Inference / solve</th><th className="px-3 py-3">Tokens / solve</th><th className="px-3 py-3">Energy / solve</th><th className="px-3 py-3">Peak</th><th className="px-3 py-3 text-right">Efficiency</th></tr></thead>
        <tbody className="divide-y divide-white/8">{report.rows.map((row) => <tr key={row.profileName} className="hover:bg-white/[0.025]">
          <td className="px-3 py-3 font-mono text-slate-400">{row.rank ? `#${row.rank}` : "-"}</td>
          <td className="max-w-72 px-3 py-3"><span className="block truncate font-medium text-white">{modelLabel(models, row.profileName)}</span><span className={`mt-1 inline-block text-[10px] uppercase ${row.eligible ? "text-emerald-300" : "text-amber-300"}`}>{row.eligible ? "eligible" : !row.qualityEligible ? "outside quality gate" : !row.solveEligible ? "solve gate missed" : "measurement incomplete"}</span></td>
          <td className="px-3 py-3 font-mono text-white">{percent(row.qualityScore)}</td>
          <td className="px-3 py-3 font-mono text-white">{percent(row.panelScore)}</td>
          <td className="px-3 py-3 font-mono text-white">{row.successes} / {row.expectedTasks}</td>
          <td className="px-3 py-3 font-mono text-slate-200">{duration(row.timePerSolveMs)}</td>
          <td className="px-3 py-3 font-mono text-slate-200">{compactNumber(row.tokensPerSolve)}</td>
          <td className="px-3 py-3"><div className="font-mono text-slate-200">{row.energyPerSolveWh == null ? "-" : `${row.energyPerSolveWh.toFixed(2)} Wh`}</div><div className="text-[10px] text-slate-600">{row.energyBasis || "pending"}</div></td>
          <td className="px-3 py-3 font-mono text-xs text-slate-400">{row.peakPowerW == null ? "-" : `${row.peakPowerW.toFixed(0)} W`} / {row.peakGpuTempC == null ? "-" : `${row.peakGpuTempC.toFixed(0)} C`}</td>
          <td className="px-3 py-3 text-right font-mono text-lg font-semibold text-white">{row.efficiencyIndex == null ? "-" : row.efficiencyIndex.toFixed(1)}</td>
        </tr>)}</tbody>
      </table>
    </div>
  </div>;
}

function ReferenceBaseline({ report, busy, onAction }: {
  report: AgenticEfficiencyReport;
  busy: boolean;
  onAction: (action: string) => Promise<void>;
}) {
  const row = report.referenceRows?.[0];
  if (!report.referenceCampaignId) return <div className="border border-violet-400/20 bg-violet-400/[0.06] p-5">
    <div className="text-xs uppercase text-violet-300">External reference</div>
    <h3 className="mt-1 font-medium text-white">Codex GPT-5.6 Sol Medium</h3>
    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">Runs the same fixed 11 tasks and official verifiers as the local finalists. Quality, time, and token cost are comparable; cloud energy is unavailable and does not enter the GPU45 efficiency rank.</p>
    <button type="button" disabled={busy} onClick={() => void onAction("reference")} className="mt-4 inline-flex h-10 items-center gap-2 border border-violet-300/30 px-4 text-sm font-medium text-violet-100 disabled:opacity-40"><Scale className="h-4 w-4" />Run Codex baseline</button>
  </div>;
  return <div className="border border-violet-400/20 bg-violet-400/[0.06] p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><div className="text-xs uppercase text-violet-300">Agent-system reference</div><div className="mt-1 font-medium text-white">{row?.displayName || "Codex GPT-5.6 Sol Medium"}</div></div>
      <span className={`border px-2 py-1 text-[10px] uppercase ${statusClass(report.referenceStatus)}`}>{report.referenceStatus}</span>
    </div>
    {row ? <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
      <ReferenceMetric label="Panel quality" value={percent(row.panelScore)} />
      <ReferenceMetric label="Verified solves" value={`${row.successes} / ${row.expectedTasks}`} />
      <ReferenceMetric label="Inference / solve" value={duration(row.timePerSolveMs)} />
      <ReferenceMetric label="Tokens / solve" value={compactNumber(row.tokensPerSolve)} />
      <ReferenceMetric label="Energy / solve" value="Cloud n/a" />
      <ReferenceMetric label="Progress" value={`${row.completedTasks} / ${row.expectedTasks}`} />
    </div> : <div className="mt-3 flex items-center gap-2 text-sm text-slate-400"><LoaderCircle className="h-4 w-4 animate-spin" />Waiting for the reference runner</div>}
  </div>;
}

function ReferenceMetric({ label, value }: { label: string; value: string }) {
  return <div className="bg-black/15 p-3"><div className="text-[10px] uppercase text-slate-500">{label}</div><div className="mt-1 font-mono text-sm text-slate-100">{value}</div></div>;
}

function ComparePanel({ leaderboard, report, models }: {
  leaderboard: ReturnType<typeof buildAgenticLeaderboard>;
  report: AgenticEfficiencyReport | null;
  models: AgenticModel[];
}) {
  const efficiencyByModel = new Map((report?.rows || []).map((row) => [row.profileName, row]));
  return <div className="mt-5 space-y-3">
    <div className="grid grid-cols-[minmax(0,1fr)_80px_80px] gap-3 px-3 text-[11px] uppercase text-slate-500"><span>Model</span><span className="text-right">Quality</span><span className="text-right">Efficiency</span></div>
    {leaderboard.map((quality) => {
      const efficient = efficiencyByModel.get(quality.profileName);
      return <div key={quality.profileName} className="grid gap-3 bg-[#121a26] p-3 md:grid-cols-[minmax(220px,1fr)_minmax(180px,.8fr)_minmax(180px,.8fr)] md:items-center">
        <div className="min-w-0"><div className="truncate text-sm font-medium text-white">{modelLabel(models, quality.profileName)}</div><div className="mt-1 truncate font-mono text-[10px] text-slate-600">{quality.profileName}</div></div>
        <div><div className="flex justify-between font-mono text-xs"><span className="text-slate-500">Capability</span><span className="text-white">{percent(quality.compositeScore)}</span></div><div className="mt-2 h-2 overflow-hidden bg-white/8"><div className="h-full bg-emerald-400" style={{ width: `${Math.max(0, Math.min(100, Number(quality.compositeScore || 0) * 100))}%` }} /></div><div className="mt-1 text-[10px] text-slate-500">11-task panel {percent(efficient?.panelScore)}</div></div>
        <div><div className="flex justify-between font-mono text-xs"><span className="text-slate-500">Efficiency</span><span className="text-white">{efficient?.efficiencyIndex == null ? "pending" : efficient.efficiencyIndex.toFixed(1)}</span></div><div className="mt-2 h-2 overflow-hidden bg-white/8"><div className="h-full bg-cyan-400" style={{ width: `${Math.max(0, Math.min(100, efficient?.efficiencyIndex || 0))}%` }} /></div></div>
      </div>;
    })}
    {(report?.referenceRows || []).map((reference) => <div key={reference.profileName} className="grid gap-3 border border-violet-400/20 bg-violet-400/[0.06] p-3 md:grid-cols-[minmax(220px,1fr)_minmax(180px,.8fr)_minmax(180px,.8fr)] md:items-center">
      <div className="min-w-0"><div className="truncate text-sm font-medium text-white">{reference.displayName}</div><div className="mt-1 text-[10px] uppercase text-violet-300">Agent-system reference</div></div>
      <div><div className="flex justify-between font-mono text-xs"><span className="text-slate-500">11-task panel</span><span className="text-white">{percent(reference.panelScore)}</span></div><div className="mt-2 h-2 overflow-hidden bg-white/8"><div className="h-full bg-violet-400" style={{ width: `${Math.max(0, Math.min(100, Number(reference.panelScore || 0) * 100))}%` }} /></div></div>
      <div><div className="flex justify-between font-mono text-xs"><span className="text-slate-500">Local GPU efficiency</span><span className="text-slate-400">not comparable</span></div><div className="mt-2 text-xs text-slate-500">Cloud power telemetry is unavailable.</div></div>
    </div>)}
    {!report?.campaignId && <div className="p-4 text-sm text-slate-500">Efficiency bars appear after the capability campaign finishes and the finalist panel runs.</div>}
  </div>;
}
