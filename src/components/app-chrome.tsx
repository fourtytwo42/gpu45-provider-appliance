"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FileText, Film, Gauge, HardDriveDownload, ImageIcon, KeyRound, Logs, Mic2, Settings2, SquareTerminal, Wrench } from "lucide-react";
import { cn } from "@/lib/cn";

const nav = [
  { href: "/", label: "Overview", icon: Gauge },
  { href: "/models", label: "Models", icon: HardDriveDownload },
  { href: "/tts", label: "TTS", icon: Mic2 },
  { href: "/whisper", label: "Whisper", icon: FileText },
  { href: "/video", label: "Video", icon: Film },
  { href: "/images", label: "Images", icon: ImageIcon },
  { href: "/keys", label: "Keys", icon: KeyRound },
  { href: "/benchmarks", label: "Benchmarks", icon: SquareTerminal },
  { href: "/logs", label: "Logs", icon: Logs },
  { href: "/settings", label: "Settings", icon: Settings2 },
];

export function AppChrome({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen bg-[#05090e] text-slate-100">
      <header className="border-b border-white/10 bg-[#070c12]">
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-4 px-4 py-4 lg:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-cyan-400/40 bg-cyan-400/10 text-cyan-300">
              <Wrench className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold tracking-wide text-white">GPU45 Appliance</div>
              <div className="text-xs text-slate-400">Provider monitoring and control</div>
            </div>
          </div>
          <nav className="flex max-w-full items-center gap-1 overflow-x-auto">
            {nav.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "inline-flex shrink-0 items-center gap-2 border px-3 py-2 text-sm transition",
                    active
                      ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-200"
                      : "border-white/10 bg-white/5 text-slate-300 hover:border-white/20 hover:bg-white/10 hover:text-white",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1680px] px-3 py-4 lg:px-5">{children}</main>
    </div>
  );
}
