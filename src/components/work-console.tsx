"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { BriefcaseBusiness, Grid2X2, List, Search, SlidersHorizontal } from "lucide-react";
import type { UnifiedJob } from "@/lib/jobs";
import { JobCard } from "./job-card";

type Tab = "active" | "queue" | "history" | "attention";

export function WorkConsole({ jobs }: { jobs: UnifiedJob[] }) {
  const [tab, setTab] = useState<Tab>("active"); const [query, setQuery] = useState(""); const [kind, setKind] = useState("all"); const [gallery, setGallery] = useState(false); const [showTests, setShowTests] = useState(false);
  const kinds = useMemo(() => Array.from(new Set(jobs.map((job) => job.kind))).sort(), [jobs]);
  const counts = useMemo(() => ({ active: jobs.filter((job) => ["running", "paused"].includes(job.status)).length, queue: jobs.filter((job) => job.status === "queued").length, attention: jobs.filter((job) => ["failed", "needs_review", "unknown"].includes(job.status)).length, history: jobs.filter((job) => ["completed", "cancelled", "stopped"].includes(job.status)).length }), [jobs]);
  const filtered = useMemo(() => jobs.filter((job) => {
    if (!showTests && /smoke|test/i.test(`${job.title} ${job.subtitle ?? ""}`)) return false;
    if (kind !== "all" && job.kind !== kind) return false;
    if (query && !`${job.title} ${job.subtitle ?? ""} ${job.model ?? ""} ${job.id}`.toLowerCase().includes(query.toLowerCase())) return false;
    if (tab === "active") return ["running", "paused"].includes(job.status);
    if (tab === "queue") return job.status === "queued";
    if (tab === "attention") return ["failed", "needs_review", "unknown"].includes(job.status);
    return ["completed", "cancelled", "stopped"].includes(job.status);
  }), [jobs, tab, query, kind, showTests]);
  return <div className="space-y-5">
    <section className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between"><div><div className="text-sm text-[#21d4fd]">Work</div><h1 className="mt-1 text-2xl font-semibold text-white">Jobs and outputs</h1><p className="mt-1 text-sm text-[#8a98aa]">Monitor every workload, recover failures, and find completed artifacts.</p></div><Link href="/outputs" className="inline-flex h-10 items-center justify-center rounded-md border border-[#2a3a4f] px-3 text-sm text-[#cdd7e3] hover:bg-[#172331]">Browse output library</Link></section>
    <div className="border-b border-[#223044]"><nav className="flex gap-5 overflow-x-auto" aria-label="Work views">{(["active", "queue", "attention", "history"] as Tab[]).map((item) => <button key={item} onClick={() => setTab(item)} className={`whitespace-nowrap border-b-2 px-1 pb-3 text-sm capitalize ${tab === item ? "border-[#21d4fd] text-white" : "border-transparent text-[#718096] hover:text-white"}`}>{item}<span className="ml-2 rounded-full bg-[#172331] px-1.5 py-0.5 text-[10px] text-[#8a98aa]">{counts[item]}</span></button>)}</nav></div>
    <section className="flex flex-col gap-3 rounded-lg bg-[#0d141e] p-3 lg:flex-row lg:items-center"><label className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-md bg-[#080d14] px-3"><Search className="h-4 w-4 text-[#617083]" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search jobs, prompts, files, or IDs" className="min-w-0 flex-1 bg-transparent text-sm text-white outline-none placeholder:text-[#617083]" /></label><div className="flex flex-wrap items-center gap-2"><SlidersHorizontal className="h-4 w-4 text-[#617083]" /><select aria-label="Filter by type" value={kind} onChange={(event) => setKind(event.target.value)} className="h-10 rounded-md border border-[#223044] bg-[#080d14] px-3 text-sm text-[#cdd7e3]"><option value="all">All types</option>{kinds.map((value) => <option value={value} key={value}>{value.replaceAll("-", " ")}</option>)}</select><label className="flex h-10 items-center gap-2 px-2 text-xs text-[#8a98aa]"><input type="checkbox" checked={showTests} onChange={(event) => setShowTests(event.target.checked)} />Show tests</label><div className="flex rounded-md bg-[#080d14] p-1"><button aria-label="List view" onClick={() => setGallery(false)} className={`p-1.5 ${!gallery ? "rounded bg-[#172331] text-[#21d4fd]" : "text-[#617083]"}`}><List className="h-4 w-4" /></button><button aria-label="Gallery view" onClick={() => setGallery(true)} className={`p-1.5 ${gallery ? "rounded bg-[#172331] text-[#21d4fd]" : "text-[#617083]"}`}><Grid2X2 className="h-4 w-4" /></button></div></div></section>
    {filtered.length ? <section className={gallery ? "grid gap-3 xl:grid-cols-2 2xl:grid-cols-3" : "space-y-2"}>{filtered.map((job) => <JobCard key={job.id} job={job} compact={!gallery} />)}</section> : <section className="rounded-xl bg-[#0d141e] py-16 text-center"><BriefcaseBusiness className="mx-auto h-8 w-8 text-[#36475c]" /><div className="mt-3 text-sm font-medium text-white">Nothing in this view</div><div className="mt-1 text-xs text-[#718096]">Try another status, type, or search term.</div></section>}
  </div>;
}
