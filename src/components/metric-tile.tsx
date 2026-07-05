import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "cyan" | "green" | "amber" | "rose" | "violet" | "slate";

const tones: Record<Tone, { icon: string; rail: string }> = {
  cyan: { icon: "text-[#21d4fd]", rail: "bg-[#21d4fd]" },
  green: { icon: "text-[#36fba1]", rail: "bg-[#36fba1]" },
  amber: { icon: "text-[#fbbf24]", rail: "bg-[#fbbf24]" },
  rose: { icon: "text-[#fb4b6b]", rail: "bg-[#fb4b6b]" },
  violet: { icon: "text-[#a78bfa]", rail: "bg-[#a78bfa]" },
  slate: { icon: "text-slate-400", rail: "bg-slate-500" },
};

export function MetricTile({ label, value, detail, icon: Icon, tone = "cyan", className }: { label: string; value: string; detail?: string; icon?: LucideIcon; tone?: Tone; className?: string }) {
  return (
    <div className={cn("relative overflow-hidden rounded-lg border border-[#223044] bg-[#0d131c] px-3 py-2.5", className)}>
      <div className={cn("absolute inset-y-0 left-0 w-0.5", tones[tone].rail)} />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[11px] uppercase tracking-[0.14em] text-[#8a98aa]">{label}</div>
          <div className="mt-1 truncate font-mono text-sm font-semibold text-[#e6edf5]">{value}</div>
          {detail ? <div className="mt-0.5 truncate text-xs text-[#8a98aa]">{detail}</div> : null}
        </div>
        {Icon ? <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", tones[tone].icon)} /> : null}
      </div>
    </div>
  );
}
