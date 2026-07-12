import { cn } from "@/lib/cn";
import type { ProviderStatus } from "@/lib/types";

const styles: Record<ProviderStatus, string> = {
  unloaded: "border-sky-400/30 bg-sky-400/10 text-sky-200",
  starting: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  ready: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
  busy: "border-cyan-400/30 bg-cyan-400/10 text-cyan-200",
  releasing: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  restoring: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  failed: "border-rose-400/30 bg-rose-400/10 text-rose-200",
};

export function StatusPill({
  status,
  children,
}: {
  status: ProviderStatus;
  children: React.ReactNode;
}) {
  return <span className={cn("inline-flex items-center rounded-md border px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.12em]", styles[status])}>{children}</span>;
}

