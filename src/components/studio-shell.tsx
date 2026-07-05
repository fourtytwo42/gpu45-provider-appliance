import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { ArrowRight, BriefcaseBusiness, Library } from "lucide-react";
import { ResourceNotice } from "./resource-notice";

type NoticeTone = "info" | "success" | "warning" | "danger";

export function StudioShell({ title, eyebrow, description, icon: Icon, accent = "#21d4fd", noticeTone = "info", noticeTitle, noticeBody, children }: { title: string; eyebrow: string; description: string; icon: LucideIcon; accent?: string; noticeTone?: NoticeTone; noticeTitle: string; noticeBody: string; children: React.ReactNode }) {
  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-[#223044] bg-[#0d131c] px-4 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-lg border bg-[#121a26]" style={{ borderColor: `${accent}66`, color: accent }}><Icon className="h-5 w-5" /></div><div><div className="text-xs font-semibold uppercase tracking-[0.16em] text-[#8a98aa]">{eyebrow}</div><h1 className="mt-1 text-xl font-semibold text-white">{title}</h1><p className="mt-1 max-w-3xl text-sm text-[#8a98aa]">{description}</p></div></div>
          <div className="flex flex-wrap gap-2"><Link href="/jobs" className="inline-flex items-center gap-2 rounded-md border border-[#223044] bg-[#121a26] px-3 py-2 text-sm text-[#cbd5e1] hover:border-[#21d4fd]/40 hover:text-cyan-100"><BriefcaseBusiness className="h-4 w-4" />Jobs</Link><Link href="/outputs" className="inline-flex items-center gap-2 rounded-md border border-[#223044] bg-[#121a26] px-3 py-2 text-sm text-[#cbd5e1] hover:border-[#21d4fd]/40 hover:text-cyan-100"><Library className="h-4 w-4" />Outputs</Link></div>
        </div>
      </section>
      <ResourceNotice tone={noticeTone} title={noticeTitle}>{noticeBody}</ResourceNotice>
      <section className="grid gap-3 md:grid-cols-3">
        <Link href="/jobs" className="rounded-lg border border-[#223044] bg-[#0d131c] p-3 text-sm text-[#cbd5e1] hover:border-[#21d4fd]/40"><div className="flex items-center justify-between"><span>Monitor active work</span><ArrowRight className="h-4 w-4 text-[#21d4fd]" /></div><div className="mt-1 text-xs text-[#8a98aa]">Queue, cancel, delete, and open outputs.</div></Link>
        <Link href="/outputs" className="rounded-lg border border-[#223044] bg-[#0d131c] p-3 text-sm text-[#cbd5e1] hover:border-[#21d4fd]/40"><div className="flex items-center justify-between"><span>Browse generated files</span><ArrowRight className="h-4 w-4 text-[#21d4fd]" /></div><div className="mt-1 text-xs text-[#8a98aa]">Audio, transcripts, images, videos, and benchmark artifacts.</div></Link>
        <Link href="/" className="rounded-lg border border-[#223044] bg-[#0d131c] p-3 text-sm text-[#cbd5e1] hover:border-[#21d4fd]/40"><div className="flex items-center justify-between"><span>Check appliance health</span><ArrowRight className="h-4 w-4 text-[#21d4fd]" /></div><div className="mt-1 text-xs text-[#8a98aa]">GPU owner, thermals, VRAM, fan, and Codex readiness.</div></Link>
      </section>
      {children}
    </div>
  );
}
