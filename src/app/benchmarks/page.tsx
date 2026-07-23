import { BenchmarkWorkspace } from "@/components/benchmark-workspace";
import { ModelsWorkspaceNav } from "@/components/models-workspace-nav";
import { listAgenticModels, listLatestAgenticResults } from "@/lib/agentic-benchmarks";
import { listBenchmarkRuns } from "@/lib/benchmarks";

export const dynamic = "force-dynamic";

export default async function BenchmarksPage() {
  const [initialRuns, agenticModels, agenticResults] = await Promise.all([
    listBenchmarkRuns(500).catch(() => []),
    listAgenticModels().catch(() => []),
    listLatestAgenticResults().catch(() => []),
  ]);
  return (
    <div className="space-y-5">
      <ModelsWorkspaceNav />
      <BenchmarkWorkspace
        initialRuns={initialRuns}
        agenticModels={agenticModels}
        agenticResults={agenticResults}
      />
    </div>
  );
}
