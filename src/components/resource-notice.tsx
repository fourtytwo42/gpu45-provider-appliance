import { AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { cn } from "@/lib/cn";

type Tone = "info" | "success" | "warning" | "danger";

const toneStyles: Record<Tone, string> = {
  info: "border-[#21d4fd]/30 bg-[#21d4fd]/10 text-cyan-100",
  success: "border-[#36fba1]/30 bg-[#36fba1]/10 text-emerald-100",
  warning: "border-[#fbbf24]/30 bg-[#fbbf24]/10 text-amber-100",
  danger: "border-[#fb4b6b]/30 bg-[#fb4b6b]/10 text-rose-100",
};

const icons = { info: Info, success: CheckCircle2, warning: AlertTriangle, danger: AlertTriangle };

export function ResourceNotice({ tone = "info", title, children, className }: { tone?: Tone; title: string; children?: React.ReactNode; className?: string }) {
  const Icon = icons[tone];
  return (
    <div className={cn("flex gap-3 rounded-lg border px-3 py-3", toneStyles[tone], className)}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0">
        <div className="text-sm font-semibold">{title}</div>
        {children ? <div className="mt-1 text-sm opacity-80">{children}</div> : null}
      </div>
    </div>
  );
}
