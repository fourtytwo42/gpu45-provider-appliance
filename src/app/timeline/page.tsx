import { Activity, Clock3, ScrollText } from "lucide-react";
import { StatusBadge } from "@/components/status-badge";
import { getTimeline } from "@/lib/timeline";

export const dynamic = "force-dynamic";

function labelDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
}

function tone(status?: string | null): "neutral" | "info" | "success" | "warning" | "danger" {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "running" || status === "queued") return "info";
  if (status === "cancelled" || status === "stopped" || status === "needs_review") return "warning";
  return "neutral";
}

export default async function TimelinePage() {
  const { events } = await getTimeline();
  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-[#223044] bg-[#0d131c] px-4 py-4"><div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-lg border border-[#21d4fd]/35 bg-[#21d4fd]/10 text-[#21d4fd]"><ScrollText className="h-5 w-5" /></div><div><h1 className="text-xl font-semibold text-white">Appliance Timeline</h1><p className="text-sm text-[#8a98aa]">Recent jobs, downloads, model events, and appliance audit activity.</p></div></div></section>
      <section className="rounded-lg border border-[#223044] bg-[#0d131c] p-4">
        <div className="space-y-3">
          {events.map((event) => <article key={event.id} className="grid gap-3 rounded-lg border border-[#223044] bg-[#070a0f] p-3 md:grid-cols-[180px_1fr]"><div className="flex items-center gap-2 text-xs text-[#8a98aa]"><Clock3 className="h-3.5 w-3.5 text-[#21d4fd]" />{labelDate(event.createdAt)}</div><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><StatusBadge tone={event.kind === "job" ? tone(event.status) : "neutral"}>{event.kind === "job" ? event.status ?? "job" : "audit"}</StatusBadge><span className="truncate font-medium text-white">{event.title}</span></div>{event.detail ? <p className="mt-1 line-clamp-2 text-sm text-[#8a98aa]">{event.detail}</p> : null}</div></article>)}
          {events.length === 0 ? <div className="flex items-center gap-2 text-sm text-[#8a98aa]"><Activity className="h-4 w-4" />No timeline events found.</div> : null}
        </div>
      </section>
    </div>
  );
}
