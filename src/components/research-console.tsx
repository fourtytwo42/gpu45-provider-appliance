"use client";

import { useEffect, useState } from "react";
import { ExternalLink, FileSearch, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { SectionCard } from "./section-card";
import { cn } from "@/lib/cn";

type RunState = "idle" | "working" | "error";
type SearchResult = { title: string; url: string; snippet: string; engine?: string; rank?: number };
type JobLead = { id: string; sourceUrl: string; company: string; title: string; location: string; remoteStatus: string; applyUrl: string; atsType?: string | null; confidence: number };

async function jsonFetch(url: string, init?: RequestInit) {
  const response = await fetch(url, { cache: "no-store", ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error ?? "Request failed");
  return data;
}

export function ResearchConsole() {
  const [state, setState] = useState<RunState>("idle");
  const [message, setMessage] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [pageText, setPageText] = useState("");
  const [pageTitle, setPageTitle] = useState("");
  const [jobLeads, setJobLeads] = useState<JobLead[]>([]);
  const [rejected, setRejected] = useState<Array<{ url: string; reason: string }>>([]);
  const [history, setHistory] = useState<Record<string, unknown>>({});

  async function run(task: () => Promise<void>, working: string) {
    setState("working");
    setMessage(working);
    try {
      await task();
      setState("idle");
    } catch (error) {
      setState("error");
      setMessage(error instanceof Error ? error.message : "Research action failed");
    }
  }

  async function refreshHistory() {
    const [searches, pages, jobs] = await Promise.all([
      jsonFetch("/api/web/history?kind=search&limit=8"),
      jsonFetch("/api/web/history?kind=page&limit=8"),
      jsonFetch("/api/web/history?kind=job&limit=8"),
    ]);
    setHistory({ searches, pages, jobs });
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void refreshHistory().catch(() => undefined);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function searchWebAction(formData: FormData) {
    await run(async () => {
      const q = String(formData.get("q") ?? "");
      const category = String(formData.get("category") ?? "general");
      const data = await jsonFetch(`/api/web/search?q=${encodeURIComponent(q)}&category=${encodeURIComponent(category)}&limit=10`);
      setResults(data.results ?? []);
      setMessage(`Search returned ${data.results?.length ?? 0} results.`);
      await refreshHistory();
    }, "Searching web.");
  }

  async function fetchUrlAction(formData: FormData) {
    await run(async () => {
      const data = await jsonFetch("/api/web/fetch", { method: "POST", body: JSON.stringify({ url: formData.get("url"), render: formData.get("render") === "on" ? "auto" : false }) });
      setPageTitle(data.page?.title ?? data.page?.finalUrl ?? "Fetched page");
      setPageText(data.text ?? "");
      setMessage(data.cached ? "Loaded cached page." : "Fetched and extracted page.");
      await refreshHistory();
    }, "Fetching URL.");
  }

  async function jobSearchAction(formData: FormData) {
    await run(async () => {
      const data = await jsonFetch("/api/web/jobs/search", { method: "POST", body: JSON.stringify({ query: formData.get("query"), remoteOnly: true, officialOnly: true, limit: 10 }) });
      setJobLeads(data.leads ?? []);
      setRejected(data.rejected ?? []);
      setMessage(`Found ${data.leads?.length ?? 0} candidate leads.`);
      await refreshHistory();
    }, "Searching official job sources.");
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(360px,0.85fr)_minmax(0,1.15fr)]">
      <section className="xl:col-span-2">
        <div className="flex flex-wrap items-center justify-between gap-3 border border-white/10 bg-[#07121a] px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center border border-cyan-400/40 bg-cyan-400/10 text-cyan-200"><FileSearch className="h-5 w-5" /></div>
            <div><h1 className="text-lg font-semibold text-white">Research</h1><p className="text-sm text-slate-400">Free web search, scraping, and official job discovery for local models.</p></div>
          </div>
          <button onClick={() => void refreshHistory()} className="inline-flex items-center gap-2 border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 hover:bg-white/10"><RefreshCw className="h-4 w-4" />Refresh</button>
        </div>
        {message ? <div className={cn("mt-3 border px-4 py-3 text-sm", state === "error" ? "border-red-400/30 bg-red-500/10 text-red-200" : "border-cyan-400/30 bg-cyan-500/10 text-cyan-100")}>{state === "working" ? "Working: " : null}{message}</div> : null}
      </section>

      <SectionCard title="Search" description="Search through local SearXNG and keep results cached in SQLite.">
        <form action={(formData) => void searchWebAction(formData)} className="grid gap-3">
          <input name="q" required className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none" placeholder="multi-agent platform engineer remote careers" />
          <select name="category" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none"><option value="general">General</option><option value="jobs">Jobs</option></select>
          <button disabled={state === "working"} className="inline-flex items-center justify-center gap-2 border border-cyan-400/40 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-400/20 disabled:opacity-50"><Search className="h-4 w-4" />Search</button>
        </form>
        <div className="mt-4 grid gap-2">
          {results.map((result) => <a key={`${result.rank}-${result.url}`} href={result.url} target="_blank" className="block border border-white/10 bg-black/20 p-3 hover:border-cyan-400/30"><div className="flex items-start justify-between gap-2"><div className="font-medium text-white">{result.title}</div><ExternalLink className="h-4 w-4 text-slate-500" /></div><div className="mt-1 truncate text-xs text-cyan-200">{result.url}</div><p className="mt-2 line-clamp-3 text-sm text-slate-400">{result.snippet}</p></a>)}
        </div>
      </SectionCard>

      <SectionCard title="Fetch URL" description="Extract readable text and links from a known page.">
        <form action={(formData) => void fetchUrlAction(formData)} className="grid gap-3">
          <input name="url" required type="url" className="border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none" placeholder="https://company.com/careers" />
          <label className="inline-flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" name="render" className="h-4 w-4 accent-cyan-400" />Use render fallback if needed</label>
          <button disabled={state === "working"} className="inline-flex items-center justify-center gap-2 border border-cyan-400/40 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-400/20 disabled:opacity-50"><FileSearch className="h-4 w-4" />Fetch</button>
        </form>
        {pageText ? <div className="mt-4 border border-white/10 bg-black/20 p-3"><div className="font-medium text-white">{pageTitle}</div><pre className="mt-2 max-h-[420px] overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-300">{pageText.slice(0, 12000)}</pre></div> : null}
      </SectionCard>

      <SectionCard title="Job Discovery" description="Search official employer and ATS pages, excluding public job boards." className="xl:col-span-2">
        <form action={(formData) => void jobSearchAction(formData)} className="flex flex-col gap-3 lg:flex-row">
          <input name="query" required className="min-w-0 flex-1 border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none" placeholder="AI platform engineer multi-agent remote" />
          <button disabled={state === "working"} className="inline-flex items-center justify-center gap-2 border border-emerald-400/40 bg-emerald-400/10 px-4 py-2 text-sm font-medium text-emerald-100 hover:bg-emerald-400/20 disabled:opacity-50"><ShieldCheck className="h-4 w-4" />Find Leads</button>
        </form>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {jobLeads.map((lead) => <article key={lead.id} className="border border-white/10 bg-black/20 p-3"><div className="text-sm font-semibold text-white">{lead.title}</div><div className="mt-1 text-xs text-slate-400">{lead.company} - {lead.location}</div><div className="mt-2 flex flex-wrap gap-2 text-[11px]"><span className="border border-emerald-400/30 px-2 py-1 text-emerald-200">{lead.remoteStatus}</span><span className="border border-cyan-400/30 px-2 py-1 text-cyan-200">{Math.round(lead.confidence * 100)}% confidence</span>{lead.atsType ? <span className="border border-violet-400/30 px-2 py-1 text-violet-200">{lead.atsType}</span> : null}</div><a className="mt-3 block truncate text-xs text-cyan-200 hover:underline" href={lead.applyUrl || lead.sourceUrl} target="_blank">{lead.applyUrl || lead.sourceUrl}</a></article>)}
        </div>
        {rejected.length ? <div className="mt-4 border border-amber-400/30 bg-amber-500/10 p-3 text-xs text-amber-100"><div className="mb-2 font-medium">Rejected or low-confidence sources</div>{rejected.slice(0, 8).map((item) => <div key={item.url} className="truncate">{item.reason}: {item.url}</div>)}</div> : null}
      </SectionCard>

      <SectionCard title="History" className="xl:col-span-2">
        <pre className="max-h-[360px] overflow-auto whitespace-pre-wrap text-xs leading-5 text-slate-300">{JSON.stringify(history, null, 2)}</pre>
      </SectionCard>
    </div>
  );
}
