import { BriefcaseBusiness, CheckCircle2, Clock3, LoaderCircle, TriangleAlert } from "lucide-react";
import { JobCard } from "@/components/job-card";
import { MetricTile } from "@/components/metric-tile";
import { ResourceNotice } from "@/components/resource-notice";
import { getUnifiedJobs } from "@/lib/jobs";

export const dynamic = "force-dynamic";

export default async function JobsPage() {
  const { jobs, summary } = await getUnifiedJobs();
  const active = jobs.filter((job) => job.status === "queued" || job.status === "running");
  const failed = jobs.filter((job) => job.status === "failed" || job.status === "needs_review");
  const activeIds = new Set(active.map((job) => job.id));
  const failedIds = new Set(failed.map((job) => job.id));
  const history = jobs.filter((job) => !activeIds.has(job.id) && !failedIds.has(job.id));

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-[#223044] bg-[#0d131c] px-4 py-4"><div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-lg border border-[#21d4fd]/35 bg-[#21d4fd]/10 text-[#21d4fd]"><BriefcaseBusiness className="h-5 w-5" /></div><div><h1 className="text-xl font-semibold text-white">Jobs</h1><p className="text-sm text-[#8a98aa]">Unified queue and history across downloads, benchmarks, audio, transcription, image, and video work.</p></div></div></section>
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><MetricTile label="Total" value={summary.total.toLocaleString()} detail="tracked jobs" icon={BriefcaseBusiness} tone="cyan" /><MetricTile label="Active" value={summary.active.toLocaleString()} detail="running now" icon={LoaderCircle} tone="green" /><MetricTile label="Queued" value={summary.queued.toLocaleString()} detail="waiting" icon={Clock3} tone="amber" /><MetricTile label="Failed" value={summary.failed.toLocaleString()} detail="needs attention" icon={TriangleAlert} tone={summary.failed > 0 ? "rose" : "slate"} /><MetricTile label="Completed" value={summary.completed.toLocaleString()} detail="finished" icon={CheckCircle2} tone="violet" /></section>
      {active.length > 0 ? <section className="space-y-3"><h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-[#8a98aa]">Active Work</h2><div className="grid gap-3 xl:grid-cols-2">{active.map((job) => <JobCard key={job.id} job={job} />)}</div></section> : <ResourceNotice tone="success" title="No active jobs">The appliance is idle from the unified queue perspective.</ResourceNotice>}
      {failed.length > 0 ? <section className="space-y-3"><h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-[#8a98aa]">Needs Attention</h2><div className="grid gap-3 xl:grid-cols-2">{failed.map((job) => <JobCard key={job.id} job={job} />)}</div></section> : null}
      <section className="space-y-3"><h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-[#8a98aa]">Recent History</h2><div className="grid gap-3 xl:grid-cols-2 2xl:grid-cols-3">{history.slice(0, 36).map((job) => <JobCard key={job.id} job={job} compact />)}</div></section>
    </div>
  );
}
