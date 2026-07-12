import { Activity, Cpu, Gauge, HardDrive, MemoryStick, Thermometer } from "lucide-react";
import { MetricTile } from "@/components/metric-tile";
import { SectionCard } from "@/components/section-card";
import { getPersistedOperationalTelemetry } from "@/lib/operational-state";
import { getResourceState } from "@/lib/resource-manager";

export const dynamic = "force-dynamic";

function bytes(value: number | null): string {
  if (value === null) return "n/a";
  return `${(value / 1024 ** 3).toFixed(1)} GB`;
}

export default async function MetricsPage() {
  const resources = await getResourceState();
  const telemetry = await getPersistedOperationalTelemetry(resources);
  const workers = Object.values(resources.workers);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricTile label="GPU junction" value={telemetry.system.gpuTempJunctionC === null ? "n/a" : `${Math.round(telemetry.system.gpuTempJunctionC)}C`} icon={Thermometer} tone="rose" />
        <MetricTile label="GPU load" value={telemetry.system.gpuUsage === null ? "n/a" : `${Math.round(telemetry.system.gpuUsage)}%`} icon={Gauge} tone="cyan" />
        <MetricTile label="VRAM used" value={bytes(telemetry.system.vramUsedBytes)} icon={MemoryStick} tone="violet" />
        <MetricTile label="Disk free" value={bytes(telemetry.system.diskFreeBytes)} icon={HardDrive} tone="green" />
      </div>
      <SectionCard title="Managed workers" description="Heavy execution processes recycle after two idle minutes">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {workers.map((worker) => (
            <div key={worker.kind} className="rounded-lg bg-black/20 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-sm font-medium text-white"><Cpu className="h-4 w-4 text-cyan-300" />{worker.kind}</div>
                <span className={worker.workerStatus === "active" ? "text-xs text-emerald-300" : "text-xs text-slate-500"}>{worker.workerStatus}</span>
              </div>
              <div className="mt-3 space-y-1 text-xs text-slate-400">
                <div>Memory <span className="float-right font-mono text-slate-200">{bytes(worker.memoryBytes)}</span></div>
                <div>Loaded model <span className="float-right max-w-36 truncate text-slate-200">{worker.loadedModel ?? "none"}</span></div>
              </div>
            </div>
          ))}
        </div>
      </SectionCard>
      <SectionCard title="Prometheus endpoint" description="Machine-readable appliance and worker metrics">
        <div className="flex items-center gap-3 rounded-lg bg-black/20 p-4 text-sm text-slate-300">
          <Activity className="h-4 w-4 text-cyan-300" />
          <code>/api/metrics</code>
        </div>
      </SectionCard>
    </div>
  );
}
