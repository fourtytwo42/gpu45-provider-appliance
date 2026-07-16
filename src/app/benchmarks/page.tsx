import { BenchmarkWorkspace } from "@/components/benchmark-workspace";
import { collectDashboardSnapshot } from "@/lib/collectors";
import { listAgenticCampaigns, listAgenticModels, listAgenticSuites } from "@/lib/agentic-benchmarks";

export const dynamic = "force-dynamic";

export default async function BenchmarksPage() {
  const snapshot = await collectDashboardSnapshot();
  const [agenticModels, agenticSuites, agenticCampaigns] = await Promise.all([
    listAgenticModels().catch(() => []), listAgenticSuites().catch(() => []), listAgenticCampaigns().catch(() => []),
  ]);
  return <BenchmarkWorkspace model={snapshot.provider.model} models={snapshot.models} initialRuns={snapshot.benchmarks} agenticModels={agenticModels} agenticSuites={agenticSuites} agenticCampaigns={agenticCampaigns} />;
}
