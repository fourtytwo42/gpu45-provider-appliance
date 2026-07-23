import { UnifiedBenchmarkConsole } from "./unified-benchmark-console";
import type { AgenticLatestResult, AgenticModel } from "@/lib/agentic-benchmarks";
import type { BenchmarkRun } from "@/lib/types";

type Props = {
  initialRuns: BenchmarkRun[];
  agenticModels: AgenticModel[];
  agenticResults: AgenticLatestResult[];
};

export function BenchmarkWorkspace(props: Props) {
  return (
    <UnifiedBenchmarkConsole
      initialRuns={props.initialRuns}
      agenticModels={props.agenticModels}
      agenticResults={props.agenticResults}
    />
  );
}
