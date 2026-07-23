import type { AgenticLatestResult, AgenticModel } from "./agentic-benchmarks";
import type { BenchmarkRun } from "./types";

export const COMMON_AGENTIC_SUITES = [
  { id: "bfcl-v4-local", label: "BFCL", tasks: 36 },
  { id: "tau-text-base", label: "Tau", tasks: 18 },
  { id: "swe-verified-mini50", label: "SWE", tasks: 8 },
  { id: "terminal-bench-2", label: "Terminal", tasks: 8 },
] as const;

export const COMMON_AGENTIC_SUITE_IDS = COMMON_AGENTIC_SUITES.map((suite) => suite.id);
export const COMMON_AGENTIC_TASKS = COMMON_AGENTIC_SUITES.reduce((total, suite) => total + suite.tasks, 0);

export type UnifiedBenchmarkRow = {
  key: string;
  profileName: string;
  displayName: string;
  modelPath?: string;
  qualificationStatus?: string;
  agentic: AgenticLatestResult | null;
  throughput: BenchmarkRun | null;
  latestAt: string | null;
};

function normalize(value: string | null | undefined): string {
  return (value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function basename(path: string | null | undefined): string {
  return (path || "").split(/[\\/]/).at(-1)?.replace(/\.gguf$/i, "") || "";
}

function runKeys(run: BenchmarkRun): string[] {
  let modelPath = "";
  try {
    modelPath = String((JSON.parse(run.optionsJson || "{}") as { modelPath?: string }).modelPath || "");
  } catch {
    modelPath = "";
  }
  return [run.modelName, basename(modelPath), modelPath].map(normalize).filter(Boolean);
}

function modelKeys(model: AgenticModel): string[] {
  return [model.name, model.description, model.servedAlias, model.modelPath, basename(model.modelPath)]
    .map(normalize)
    .filter(Boolean);
}

function newestDate(agentic: AgenticLatestResult | null, throughput: BenchmarkRun | null): string | null {
  const values = [agentic?.completedAt || agentic?.updatedAt, throughput?.createdAt].filter(Boolean) as string[];
  return values.sort((left, right) => Date.parse(right) - Date.parse(left))[0] || null;
}

export function buildUnifiedBenchmarkRows(
  models: AgenticModel[],
  throughputRuns: BenchmarkRun[],
  agenticResults: AgenticLatestResult[],
): UnifiedBenchmarkRow[] {
  const newestThroughputRuns = [...throughputRuns].sort(
    (left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt),
  );
  const latestAgenticByProfile = new Map(agenticResults.map((result) => [result.profileName, result]));
  const unusedRuns = new Set(newestThroughputRuns);
  const claimedAgenticProfiles = new Set<string>();
  const rows: UnifiedBenchmarkRow[] = models.map((model) => {
    const keys = new Set(modelKeys(model));
    const throughput = newestThroughputRuns.find((run) => unusedRuns.has(run) && runKeys(run).some((key) => keys.has(key))) || null;
    if (throughput) unusedRuns.delete(throughput);
    const agentic = latestAgenticByProfile.get(model.name) || null;
    if (agentic) claimedAgenticProfiles.add(agentic.profileName);
    return {
      key: model.name,
      profileName: model.name,
      displayName: model.description || model.servedAlias || model.name,
      modelPath: model.modelPath,
      qualificationStatus: model.qualification?.status,
      agentic,
      throughput,
      latestAt: newestDate(agentic, throughput),
    };
  });

  for (const agentic of agenticResults) {
    if (claimedAgenticProfiles.has(agentic.profileName)) continue;
    rows.push({
      key: `agentic:${agentic.profileName}`,
      profileName: agentic.profileName,
      displayName: agentic.displayName || agentic.profileName,
      agentic,
      throughput: null,
      latestAt: newestDate(agentic, null),
    });
  }

  return rows.sort((left, right) => {
    const leftScore = left.agentic?.compositeScore;
    const rightScore = right.agentic?.compositeScore;
    if (leftScore !== null && leftScore !== undefined && rightScore !== null && rightScore !== undefined) {
      if (leftScore !== rightScore) return rightScore - leftScore;
    } else if (leftScore !== null && leftScore !== undefined) {
      return -1;
    } else if (rightScore !== null && rightScore !== undefined) {
      return 1;
    }
    const leftSpeed = left.throughput?.generationTokensPerSecond;
    const rightSpeed = right.throughput?.generationTokensPerSecond;
    if (leftSpeed !== undefined && rightSpeed !== undefined && leftSpeed !== rightSpeed) return rightSpeed - leftSpeed;
    if (leftSpeed !== undefined) return -1;
    if (rightSpeed !== undefined) return 1;
    return left.displayName.localeCompare(right.displayName);
  });
}
