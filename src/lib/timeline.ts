import { prisma } from "./db";
import { getUnifiedJobs } from "./jobs";

export type TimelineEvent = {
  id: string;
  kind: "job" | "audit";
  title: string;
  detail?: string | null;
  status?: string | null;
  createdAt: string;
};

export async function getTimeline(): Promise<{ events: TimelineEvent[] }> {
  const [audit, unified] = await Promise.all([
    prisma.auditLog.findMany({ orderBy: { createdAt: "desc" }, take: 80 }).catch(() => []),
    getUnifiedJobs().catch(() => ({ jobs: [], summary: { total: 0, active: 0, queued: 0, failed: 0, completed: 0 } })),
  ]);
  const events: TimelineEvent[] = [];
  for (const item of audit) events.push({ id: `audit:${item.id}`, kind: "audit", title: item.action, detail: `${item.subject}${item.details ? ` - ${item.details}` : ""}`, createdAt: item.createdAt.toISOString() });
  for (const job of unified.jobs.slice(0, 80)) events.push({ id: `job:${job.id}`, kind: "job", title: job.title, detail: job.subtitle ?? job.error ?? job.kind, status: job.status, createdAt: job.updatedAt ?? job.finishedAt ?? job.createdAt ?? new Date().toISOString() });
  events.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  return { events: events.slice(0, 120) };
}
