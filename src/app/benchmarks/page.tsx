import { BenchmarkConsole } from "@/components/benchmark-console";
import { collectDashboardSnapshot } from "@/lib/collectors";

export const dynamic = "force-dynamic";

export default async function BenchmarksPage() {
  const snapshot = await collectDashboardSnapshot();
  return <BenchmarkConsole model={snapshot.provider.model} models={snapshot.models} initialRuns={snapshot.benchmarks} />;
}
