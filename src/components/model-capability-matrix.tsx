import { Bot, BrainCircuit, CheckCircle2, Eye, Gauge, Layers3, TriangleAlert, Wrench } from "lucide-react";
import type { ModelCapability } from "@/lib/model-capabilities";
import { StatusBadge } from "./status-badge";

function bool(value: boolean): string { return value ? "yes" : "no"; }
function tps(value?: number | null): string { return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "n/a"; }

export function ModelCapabilityMatrix({ capabilities }: { capabilities: ModelCapability[] }) {
  return (
    <section className="rounded-lg border border-[#223044] bg-[#0d131c] p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-white">Model capability matrix</h2><p className="mt-1 text-sm text-[#8a98aa]">Codex readiness, context, MTP, vision, and best observed benchmark metrics.</p></div><Bot className="h-5 w-5 text-[#21d4fd]" /></div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-[0.14em] text-[#617083]"><tr className="border-b border-[#223044]"><th className="py-2 pr-4">Model</th><th className="px-3 py-2">Codex</th><th className="px-3 py-2">Context</th><th className="px-3 py-2">MTP</th><th className="px-3 py-2">Vision</th><th className="px-3 py-2">Tools</th><th className="px-3 py-2">Reasoning</th><th className="px-3 py-2">Best tok/s</th><th className="px-3 py-2">Notes</th></tr></thead>
          <tbody>
            {capabilities.map((model) => <tr key={model.name} className="border-b border-[#223044]/70 last:border-0"><td className="max-w-[320px] py-3 pr-4"><div className="truncate font-medium text-white" title={model.name}>{model.name}</div><div className="mt-1 flex flex-wrap gap-1.5">{model.active ? <StatusBadge tone="success">active</StatusBadge> : null}{model.served ? <StatusBadge tone="info">served</StatusBadge> : null}{model.alias ? <span className="truncate font-mono text-[11px] text-[#617083]">{model.alias}</span> : null}</div></td><td className="px-3 py-3"><StatusBadge tone={model.codex === "ready" ? "success" : model.codex === "check" ? "warning" : "danger"}>{model.codex}</StatusBadge></td><td className="px-3 py-3 font-mono text-[#cbd5e1]">{model.maxContext.toLocaleString()}</td><td className="px-3 py-3 text-[#cbd5e1]"><span className="inline-flex items-center gap-1"><Layers3 className="h-3.5 w-3.5 text-[#a78bfa]" />{bool(model.mtp)}</span></td><td className="px-3 py-3 text-[#cbd5e1]"><span className="inline-flex items-center gap-1"><Eye className="h-3.5 w-3.5 text-[#21d4fd]" />{bool(model.vision)}</span></td><td className="px-3 py-3 text-[#cbd5e1]"><span className="inline-flex items-center gap-1"><Wrench className="h-3.5 w-3.5 text-[#fbbf24]" />{model.toolCalling}</span></td><td className="px-3 py-3 text-[#cbd5e1]"><span className="inline-flex items-center gap-1"><BrainCircuit className="h-3.5 w-3.5 text-[#36fba1]" />{model.reasoning}</span></td><td className="px-3 py-3 font-mono text-[#cbd5e1]"><span className="inline-flex items-center gap-1"><Gauge className="h-3.5 w-3.5 text-[#21d4fd]" />{tps(model.bestPromptTps)} / {tps(model.bestDecodeTps)}</span></td><td className="max-w-[360px] px-3 py-3 text-[#8a98aa]">{model.knownIssue ? <span className="inline-flex gap-1"><TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#fbbf24]" />{model.knownIssue}</span> : <span className="inline-flex gap-1"><CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[#36fba1]" />No known local issue</span>}</td></tr>)}
          </tbody>
        </table>
      </div>
    </section>
  );
}
