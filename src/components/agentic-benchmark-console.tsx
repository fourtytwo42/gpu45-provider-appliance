"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, CircleAlert, Download, FlaskConical, LoaderCircle, Pause, Play, RefreshCw, Rocket, Square } from "lucide-react";
import type { AgenticCampaign, AgenticCampaignDetail, AgenticModel, AgenticSuite } from "@/lib/agentic-benchmarks";
import { buildAgenticLeaderboard, type AgenticRankingSummary, type AgenticRunSummary } from "@/lib/agentic-leaderboard";

type Props = { initialModels: AgenticModel[]; initialSuites: AgenticSuite[]; initialCampaigns: AgenticCampaign[] };

function statusClass(status?: string) {
  if (status === "eligible" || status === "completed") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-300";
  if (status === "failed") return "border-rose-400/30 bg-rose-400/10 text-rose-300";
  if (status === "running") return "border-cyan-400/30 bg-cyan-400/10 text-cyan-300";
  return "border-amber-400/30 bg-amber-400/10 text-amber-300";
}

function formatApplianceTime(value: string) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago", year: "numeric", month: "numeric", day: "numeric",
    hour: "numeric", minute: "2-digit", second: "2-digit",
  }).format(new Date(value));
}

function percent(value?: number | null) {
  return value == null ? "-" : `${(value * 100).toFixed(1)}%`;
}

export function AgenticBenchmarkConsole({ initialModels, initialSuites, initialCampaigns }: Props) {
  const [models, setModels] = useState(initialModels);
  const [suites, setSuites] = useState(initialSuites);
  const [campaigns, setCampaigns] = useState(initialCampaigns);
  const [selectedModels, setSelectedModels] = useState<string[]>(initialModels.filter((model) => model.qualification?.status === "eligible").map((model) => model.name));
  const commonSuiteIds = useMemo(() => new Set(["bfcl-v4-local", "tau-text-base", "swe-verified-mini50", "terminal-bench-2"]), []);
  const [selectedSuites, setSelectedSuites] = useState<string[]>(initialSuites.filter((suite) => commonSuiteIds.has(suite.id)).map((suite) => suite.id));
  const [detail, setDetail] = useState<AgenticCampaignDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const suiteById = useMemo(() => new Map(suites.map((suite) => [suite.id, suite])), [suites]);
  const leaderboard = useMemo(() => detail ? buildAgenticLeaderboard(
    detail.runs as unknown as AgenticRunSummary[],
    detail.ranking as unknown as AgenticRankingSummary[],
  ) : [], [detail]);
  const eligible = models.filter((model) => model.qualification?.status === "eligible").length;
  const active = campaigns.find((campaign) => ["running", "queued", "paused"].includes(campaign.status));

  const refresh = useCallback(async () => {
    const [modelResponse, suiteResponse, campaignResponse] = await Promise.all([
      fetch("/api/agentic-benchmarks/models", { cache: "no-store" }),
      fetch("/api/agentic-benchmarks/suites", { cache: "no-store" }),
      fetch("/api/agentic-benchmarks", { cache: "no-store" }),
    ]);
    const [modelPayload, suitePayload, campaignPayload] = await Promise.all([modelResponse.json(), suiteResponse.json(), campaignResponse.json()]);
    if (!modelResponse.ok || !suiteResponse.ok || !campaignResponse.ok) throw new Error(modelPayload.error || suitePayload.error || campaignPayload.error || "Benchmark coordinator unavailable");
    setModels(modelPayload.models); setSuites(suitePayload.suites); setCampaigns(campaignPayload.campaigns);
    if (detail) {
      const response = await fetch(`/api/agentic-benchmarks/${detail.campaign.id}`, { cache: "no-store" });
      if (response.ok) setDetail(await response.json());
    }
  }, [detail]);

  useEffect(() => {
    const timer = window.setInterval(() => void refresh().catch((cause) => setError(cause instanceof Error ? cause.message : "Refresh failed")), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (detail || !active) return;
    void fetch(`/api/agentic-benchmarks/${active.id}`, { cache: "no-store" })
      .then(async (response) => { if (response.ok) setDetail(await response.json()); })
      .catch(() => undefined);
  }, [active, detail]);

  async function runAction(url: string, body: object) {
    setBusy(true); setError(null);
    try {
      const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Action failed");
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Action failed"); }
    finally { setBusy(false); }
  }

  async function createCampaign() {
    await runAction("/api/agentic-benchmarks", { name: `Common campaign ${new Date().toLocaleDateString()}`, preset: "common", profileNames: selectedModels, suiteIds: selectedSuites });
  }

  const visibleCampaigns = useMemo(() => {
    const automaticSeen = new Set<string>();
    return campaigns.filter((campaign) => {
      if (campaign.preset !== "automatic-model-smoke") return true;
      if (automaticSeen.has(campaign.name)) return false;
      automaticSeen.add(campaign.name);
      return true;
    });
  }, [campaigns]);

  return <div className="space-y-5">
    <section className="grid gap-3 md:grid-cols-4">
      <div className="bg-[#0d131c] p-4"><div className="text-xs uppercase text-slate-500">Catalog</div><div className="mt-2 text-2xl font-semibold text-white">{models.length}</div><div className="text-xs text-slate-500">dynamic profiles</div></div>
      <div className="bg-[#0d131c] p-4"><div className="text-xs uppercase text-slate-500">Eligible</div><div className="mt-2 text-2xl font-semibold text-emerald-300">{eligible}</div><div className="text-xs text-slate-500">smoke qualified</div></div>
      <div className="bg-[#0d131c] p-4"><div className="text-xs uppercase text-slate-500">Suites</div><div className="mt-2 text-2xl font-semibold text-white">{suites.length}</div><div className="text-xs text-slate-500">pinned manifests</div></div>
      <div className="bg-[#0d131c] p-4"><div className="text-xs uppercase text-slate-500">Scheduler</div><div className="mt-2 flex items-center gap-2 text-sm font-medium text-cyan-300"><Activity className="h-4 w-4" />{active ? active.status : "idle"}</div><div className="mt-2 text-xs text-slate-500">priority 10, preemptible</div></div>
    </section>

    {error && <div className="flex items-center gap-2 border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-200"><CircleAlert className="h-4 w-4" />{error}</div>}

    <div className="grid gap-5 xl:grid-cols-[1.15fr_.85fr]">
      <section className="bg-[#0d131c] p-5">
        <div className="flex items-center justify-between"><div><h2 className="font-semibold text-white">Model qualification</h2><p className="mt-1 text-sm text-slate-500">New or changed profiles are tested automatically.</p></div><button title="Refresh model qualifications" onClick={() => void refresh()} className="p-2 text-slate-400 hover:bg-white/5 hover:text-white"><RefreshCw className="h-4 w-4" /></button></div>
        <div className="mt-4 divide-y divide-white/8 border-y border-white/8">{models.map((model) => {
          const status = model.qualification?.status || "pending";
          return <div key={model.name} className="grid gap-3 py-3 md:grid-cols-[auto_1fr_auto] md:items-center">
            <input aria-label={`Select ${model.name}`} type="checkbox" checked={selectedModels.includes(model.name)} onChange={(event) => setSelectedModels((items) => event.target.checked ? [...items, model.name] : items.filter((item) => item !== model.name))} className="h-4 w-4 accent-cyan-400" />
            <div className="min-w-0"><div className="truncate text-sm font-medium text-slate-100">{model.description || model.name}</div><div className="mt-1 flex flex-wrap gap-3 font-mono text-[11px] text-slate-500"><span>{model.backend || "unknown"}</span><span>{model.ctxSize ? `${Math.round(model.ctxSize / 1024)}K context` : "context unknown"}</span><span>{model.modelSizeBytes ? `${(model.modelSizeBytes / 1024 ** 3).toFixed(1)} GB` : ""}</span></div>{model.qualification?.remediation && <div className="mt-1 text-xs text-rose-300">{model.qualification.remediation}</div>}</div>
            <div className="flex items-center justify-end gap-2"><span className={`border px-2 py-1 text-[10px] uppercase ${statusClass(status)}`}>{status}</span>{status === "failed" && <button title="Run compatibility smoke again" disabled={busy} onClick={() => void runAction("/api/agentic-benchmarks/models", { profileName: model.name })} className="p-2 text-slate-400 hover:bg-white/5 hover:text-white"><RefreshCw className="h-4 w-4" /></button>}</div>
          </div>;
        })}</div>
      </section>

      <section className="bg-[#0d131c] p-5">
        <h2 className="font-semibold text-white">Common campaign</h2><p className="mt-1 text-sm text-slate-500">Runs only when you start it and yields to Codex.</p>
        <div className="mt-4 space-y-2">{suites.filter((suite) => commonSuiteIds.has(suite.id)).map((suite) => <label key={suite.id} className="flex items-center gap-3 bg-[#121a26] p-3"><input type="checkbox" checked={selectedSuites.includes(suite.id)} onChange={(event) => setSelectedSuites((items) => event.target.checked ? [...items, suite.id] : items.filter((item) => item !== suite.id))} className="h-4 w-4 accent-cyan-400" /><span className="flex-1"><span className="block text-sm text-slate-100">{suite.name}</span><span className="text-xs text-slate-500">{suite.taskCount ?? "dynamic"} tasks · {suite.requiresDocker ? "isolated Docker" : "bare metal harness"}</span></span></label>)}</div>
        <button disabled={busy || selectedModels.length === 0 || selectedSuites.length === 0} onClick={() => void createCampaign()} className="mt-4 flex w-full items-center justify-center gap-2 bg-cyan-400 px-4 py-2.5 text-sm font-semibold text-[#071018] hover:bg-cyan-300 disabled:opacity-40">{busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />}Start common campaign</button>
      </section>
    </div>

    <section className="bg-[#0d131c] p-5"><div className="flex items-center justify-between"><div><h2 className="font-semibold text-white">Campaigns</h2><p className="mt-1 text-sm text-slate-500">Persistent across browser closure, service restart, and reboot.</p></div></div>
      <div className="mt-4 divide-y divide-white/8 border-y border-white/8">{visibleCampaigns.length === 0 ? <div className="py-10 text-center text-sm text-slate-500">No campaigns yet.</div> : visibleCampaigns.map((campaign) => <div key={campaign.id} className="grid gap-3 py-3 lg:grid-cols-[1fr_auto_auto] lg:items-center"><button className="min-w-0 text-left" onClick={async () => { const response = await fetch(`/api/agentic-benchmarks/${campaign.id}`); if (response.ok) setDetail(await response.json()); }}><span className="block truncate text-sm font-medium text-white">{campaign.name}</span><span className="mt-1 block font-mono text-[11px] text-slate-500">{formatApplianceTime(campaign.created_at)} · {campaign.progress?.total ? `${campaign.progress.completed}/${campaign.progress.total} tasks · ` : ""}{Object.entries(campaign.runSummary || {}).map(([key, value]) => `${value} ${key}`).join(" · ") || "not started"}</span></button><span className={`w-fit border px-2 py-1 text-[10px] uppercase ${statusClass(campaign.status)}`}>{campaign.status}</span><div className="flex gap-1">{campaign.status === "running" && <button title="Pause after current task" onClick={() => void runAction(`/api/agentic-benchmarks/${campaign.id}/action`, { action: "pause" })} className="p-2 text-amber-300 hover:bg-white/5"><Pause className="h-4 w-4" /></button>}{["paused", "queued"].includes(campaign.status) && <button title="Start or resume campaign" onClick={() => void runAction(`/api/agentic-benchmarks/${campaign.id}/action`, { action: campaign.status === "paused" ? "resume" : "start" })} className="p-2 text-emerald-300 hover:bg-white/5"><Play className="h-4 w-4" /></button>}{!["completed", "failed", "cancelled"].includes(campaign.status) && <button title="Cancel campaign" onClick={() => void runAction(`/api/agentic-benchmarks/${campaign.id}/action`, { action: "cancel" })} className="p-2 text-rose-300 hover:bg-white/5"><Square className="h-4 w-4" /></button>}</div></div>)}</div>
    </section>

    {detail && <section className="bg-[#0d131c] p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold text-white">{detail.campaign.name}</h2><p className="mt-1 text-sm text-slate-500">Model comparison and rolling suite scores. Final ranks appear after every common suite completes.</p></div><div className="flex items-center gap-1">{["json", "csv", "markdown"].map((format) => <a key={format} title={`Export ${format}`} href={`/api/agentic-benchmarks/${detail.campaign.id}/export?format=${format}`} className="inline-flex items-center gap-1 p-2 text-xs uppercase text-slate-300 hover:bg-white/5"><Download className="h-3.5 w-3.5" />{format}</a>)}{detail.campaign.preset === "common" && detail.campaign.status === "completed" && <button title="Queue top-three qualification" onClick={() => void runAction(`/api/agentic-benchmarks/${detail.campaign.id}/action`, { action: "promote" })} className="p-2 text-cyan-300 hover:bg-white/5"><Rocket className="h-4 w-4" /></button>}<button onClick={() => setDetail(null)} className="p-2 text-sm text-slate-400 hover:text-white">Close</button></div></div>
      <div className="mt-4 overflow-x-auto border-y border-white/8">
        <table className="w-full min-w-[1120px] border-collapse text-left text-sm">
          <thead className="bg-[#121a26] text-[11px] uppercase text-slate-500"><tr><th className="px-3 py-3">Rank</th><th className="px-3 py-3">Model</th><th className="px-3 py-3">Progress</th>{detail.campaign.preset === "common" && ["bfcl-v4-local", "tau-text-base", "swe-verified-mini50", "terminal-bench-2"].map((suiteId) => <th key={suiteId} className="px-3 py-3">{suiteById.get(suiteId)?.name || suiteId}</th>)}<th className="px-3 py-3">Pass / fail</th><th className="px-3 py-3">Invalid</th><th className="px-3 py-3 text-right">Composite</th></tr></thead>
          <tbody className="divide-y divide-white/8">{leaderboard.map((row) => <tr key={row.profileName} className="hover:bg-white/[0.025]"><td className="px-3 py-3 font-mono text-slate-400">{row.rank == null ? "-" : `#${row.rank}`}</td><td className="max-w-64 px-3 py-3"><span className="block truncate font-medium text-slate-100" title={row.profileName}>{models.find((model) => model.name === row.profileName)?.description || row.profileName}</span><span className="mt-1 block truncate font-mono text-[10px] text-slate-600">{row.profileName}</span></td><td className="px-3 py-3"><div className="font-mono text-xs text-slate-200">{row.completedTasks.toLocaleString()} / {row.expectedTasks.toLocaleString()}</div><div className="mt-2 h-1.5 w-28 overflow-hidden bg-white/8"><div className="h-full bg-cyan-400" style={{ width: `${row.expectedTasks ? Math.min(100, row.completedTasks / row.expectedTasks * 100) : 0}%` }} /></div></td>{detail.campaign.preset === "common" && ["bfcl-v4-local", "tau-text-base", "swe-verified-mini50", "terminal-bench-2"].map((suiteId) => { const run = row.suites[suiteId]; return <td key={suiteId} className="px-3 py-3"><div className="font-mono text-sm text-white">{percent(run?.score)}</div><div className="mt-1 text-[10px] text-slate-500">{run ? `${Number(run.completed_tasks || 0).toLocaleString()}/${Number(run.expected_tasks || 0).toLocaleString()} · ${run.status}` : "not scheduled"}</div></td>; })}<td className="px-3 py-3 font-mono text-xs"><span className="text-emerald-300">{row.passedTasks.toLocaleString()}</span><span className="px-1 text-slate-600">/</span><span className="text-rose-300">{row.failedTasks.toLocaleString()}</span></td><td className="px-3 py-3 font-mono text-xs text-slate-300">{percent(row.invalidOutputRate)}</td><td className="px-3 py-3 text-right font-mono text-base font-semibold text-white">{percent(row.compositeScore)}</td></tr>)}</tbody>
        </table>
      </div>
      {detail.campaign.preset !== "common" && <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{detail.runs.map((run) => <div key={String(run.id)} className="bg-[#121a26] p-3"><div className="truncate text-sm text-slate-100">{String(run.profile_name)}</div><div className="mt-1 text-xs text-slate-500">{String(run.suite_id)}</div><div className="mt-3 flex items-center justify-between"><span className={`border px-2 py-1 text-[10px] uppercase ${statusClass(String(run.status))}`}>{String(run.status)}</span><span className="font-mono text-sm text-white">{run.score == null ? "-" : `${(Number(run.score) * 100).toFixed(1)}%`}</span></div></div>)}</div>}{detail.artifacts?.length > 0 && <div className="mt-5"><h3 className="text-sm font-medium text-white">Recent artifacts</h3><div className="mt-2 grid gap-2 md:grid-cols-2">{detail.artifacts.slice(0, 12).map((artifact) => <a key={artifact.id} href={`/api/agentic-benchmarks/${detail.campaign.id}/artifacts/${artifact.id}`} className="flex items-center justify-between bg-[#121a26] px-3 py-2 text-xs text-slate-300 hover:text-cyan-200"><span className="truncate">{artifact.kind}: {artifact.relative_path.split("/").at(-1)}</span><span className="ml-3 font-mono text-slate-500">{Math.ceil(artifact.size_bytes / 1024)} KB</span></a>)}</div></div>}</section>}
  </div>;
}
