import Link from "next/link";
import { Download, FileAudio, FileText, Film, ImageIcon, Library, Music2, TerminalSquare } from "lucide-react";
import { MetricTile } from "@/components/metric-tile";
import { StatusBadge } from "@/components/status-badge";
import { getOutputs } from "@/lib/outputs";
import type { OutputKind } from "@/lib/outputs";

export const dynamic = "force-dynamic";

const icons = { audio: FileAudio, audiobook: FileAudio, transcript: FileText, image: ImageIcon, video: Film, music: Music2, benchmark: TerminalSquare, download: Download, presentation: FileAudio };

function labelDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default async function OutputsPage({ searchParams }: { searchParams?: Promise<{ kind?: string }> }) {
  const params = await searchParams;
  const selectedKind = params?.kind as OutputKind | undefined;
  const { outputs, kinds } = await getOutputs();
  const filtered = selectedKind ? outputs.filter((output) => output.kind === selectedKind) : outputs;
  const available = outputs.filter((output) => output.status === "available").length;
  const recordOnly = outputs.length - available;

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-[#223044] bg-[#0d131c] px-4 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-lg border border-[#21d4fd]/35 bg-[#21d4fd]/10 text-[#21d4fd]"><Library className="h-5 w-5" /></div><div><h1 className="text-xl font-semibold text-white">Output Library</h1><p className="text-sm text-[#8a98aa]">Generated media, transcripts, benchmarks, and completed artifacts in one place.</p></div></div>
          <div className="flex flex-wrap gap-2"><Link href="/outputs" className="rounded-md border border-[#223044] bg-[#121a26] px-3 py-1.5 text-sm text-[#cbd5e1] hover:border-[#21d4fd]/40">All</Link>{kinds.map((kind) => <Link key={kind} href={`/outputs?kind=${kind}`} className="rounded-md border border-[#223044] bg-[#121a26] px-3 py-1.5 text-sm capitalize text-[#cbd5e1] hover:border-[#21d4fd]/40">{kind}</Link>)}</div>
        </div>
      </section>
      <section className="grid gap-3 sm:grid-cols-3"><MetricTile label="Outputs" value={outputs.length.toLocaleString()} detail="known artifacts" icon={Library} tone="cyan" /><MetricTile label="Downloadable" value={available.toLocaleString()} detail="direct output links" icon={Download} tone="green" /><MetricTile label="Records" value={recordOnly.toLocaleString()} detail="metadata only" icon={TerminalSquare} tone="violet" /></section>
      <section className="grid gap-3 xl:grid-cols-2 2xl:grid-cols-3">
        {filtered.map((output) => {
          const Icon = icons[output.kind];
          return <article key={output.id} className="rounded-lg border border-[#223044] bg-[#0d131c] p-4"><div className="flex gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-[#223044] bg-[#121a26] text-[#21d4fd]"><Icon className="h-5 w-5" /></div><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><StatusBadge tone={output.status === "available" ? "success" : "neutral"}>{output.status === "available" ? "available" : "record"}</StatusBadge><span className="text-xs uppercase tracking-[0.14em] text-[#617083]">{output.kind}</span></div><h2 className="mt-2 truncate text-sm font-semibold text-white" title={output.title}>{output.title}</h2>{output.subtitle ? <p className="mt-1 line-clamp-2 text-sm text-[#8a98aa]" title={output.subtitle}>{output.subtitle}</p> : null}<div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-xs text-[#617083]"><div className="flex min-w-0 flex-wrap gap-x-4 gap-y-1">{output.model ? <span className="truncate">Model: {output.model}</span> : null}<span>{labelDate(output.createdAt)}</span></div>{output.url ? <a href={output.url} className="inline-flex items-center gap-1 rounded-md border border-[#21d4fd]/30 bg-[#21d4fd]/10 px-2 py-1 text-[#a5f3fc]"><Download className="h-3.5 w-3.5" />Open</a> : null}</div></div></div></article>;
        })}
      </section>
    </div>
  );
}
