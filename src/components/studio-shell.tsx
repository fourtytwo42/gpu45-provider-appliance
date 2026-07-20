import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { ResourceNotice } from "./resource-notice";

type NoticeTone = "info" | "success" | "warning" | "danger";
const studioLinks = [
  { href: "/studio/speech", label: "Speech" }, { href: "/studio/audiobooks", label: "Audiobooks" },
  { href: "/studio/presentations", label: "Presentations" }, { href: "/studio/voices", label: "Voice Library" },
  { href: "/studio/training", label: "Training" }, { href: "/whisper", label: "Transcription" },
  { href: "/studio/music", label: "Music" }, { href: "/images", label: "Images" }, { href: "/video", label: "Video" }, { href: "/research", label: "Research" },
];

export function StudioShell({ title, eyebrow, description, icon: Icon, accent = "#21d4fd", noticeTone = "info", noticeTitle, noticeBody, activeHref, children }: { title: string; eyebrow: string; description: string; icon: LucideIcon; accent?: string; noticeTone?: NoticeTone; noticeTitle: string; noticeBody: string; activeHref?: string; children: React.ReactNode }) {
  return <div className="min-w-0 space-y-5"><section className="space-y-4 border-b border-[#223044] pb-5"><div className="flex items-start gap-3"><div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#172331]" style={{ color: accent }}><Icon className="h-5 w-5" /></div><div><div className="text-sm" style={{ color: accent }}>{eyebrow}</div><h1 className="mt-1 text-2xl font-semibold text-white">{title}</h1><p className="mt-1 max-w-3xl text-sm leading-6 text-[#8a98aa]">{description}</p></div></div><nav aria-label="Studio tools" className="flex max-w-full gap-1 overflow-x-auto rounded-lg bg-[#0d141e] p-1">{studioLinks.map((item) => <Link key={item.href} href={item.href} className={`whitespace-nowrap rounded-md px-3 py-2 text-xs transition ${activeHref === item.href ? "bg-[#172331] text-[#21d4fd]" : "text-[#8a98aa] hover:bg-[#172331] hover:text-white"}`}>{item.label}</Link>)}</nav></section><ResourceNotice tone={noticeTone} title={noticeTitle}>{noticeBody}</ResourceNotice>{children}</div>;
}
