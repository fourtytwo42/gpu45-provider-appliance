import { ModelCapabilityMatrix } from "@/components/model-capability-matrix";
import { ModelManager } from "@/components/model-manager";
import { ModelsWorkspaceNav } from "@/components/models-workspace-nav";
import { collectDashboardSnapshot } from "@/lib/collectors";
import { deriveModelCapabilities } from "@/lib/model-capabilities";

export const dynamic = "force-dynamic";

export default async function ModelsPage() {
  const snapshot = await collectDashboardSnapshot();
  const capabilities = deriveModelCapabilities(snapshot.models, snapshot.benchmarks);
  return <div className="space-y-5"><ModelsWorkspaceNav /><ModelCapabilityMatrix capabilities={capabilities} /><ModelManager initialModels={snapshot.models} diskFreeBytes={snapshot.system.diskFreeBytes} /></div>;
}
