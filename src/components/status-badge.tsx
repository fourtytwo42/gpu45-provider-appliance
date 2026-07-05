import { cn } from "@/lib/cn";

type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "creative";

const tones: Record<Tone, string> = {
  neutral: "border-[#223044] bg-[#121a26] text-[#cbd5e1]",
  info: "border-[#21d4fd]/35 bg-[#21d4fd]/10 text-[#a5f3fc]",
  success: "border-[#36fba1]/35 bg-[#36fba1]/10 text-[#bbf7d0]",
  warning: "border-[#fbbf24]/35 bg-[#fbbf24]/10 text-[#fde68a]",
  danger: "border-[#fb4b6b]/35 bg-[#fb4b6b]/10 text-[#fecdd3]",
  creative: "border-[#a78bfa]/35 bg-[#a78bfa]/10 text-[#ddd6fe]",
};

export function StatusBadge({ tone = "neutral", children, className }: { tone?: Tone; children: React.ReactNode; className?: string }) {
  return <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium", tones[tone], className)}>{children}</span>;
}
