import { DEFAULT_BENCHMARK_PROMPT, runConfiguredBenchmark } from "../lib/benchmarks";
import { prisma } from "../lib/db";

type SavedOptions = {
  model?: string;
  modelPath?: string;
  prompt?: string;
  maxOutputTokens?: number;
  temperature?: number;
  repetitions?: number;
};

function isComparableRun(optionsJson: string | null, modelName: string, modelPath: string): boolean {
  if (!optionsJson) return false;
  try {
    const options = JSON.parse(optionsJson) as SavedOptions;
    return options.model === modelName
      && options.modelPath === modelPath
      && options.prompt === DEFAULT_BENCHMARK_PROMPT
      && options.maxOutputTokens === 2048
      && options.temperature === 0
      && options.repetitions === 2;
  } catch {
    return false;
  }
}

async function main(): Promise<void> {
  const profiles = await prisma.launchProfile.findMany({ orderBy: { name: "asc" } });
  const activeProfile = profiles.find((profile) => profile.active);
  const orderedProfiles = [
    ...profiles.filter((profile) => !profile.active),
    ...profiles.filter((profile) => profile.active),
  ];
  const failures: Array<{ model: string; error: string }> = [];

  console.log(JSON.stringify({
    event: "suite.started",
    models: orderedProfiles.length,
    restoreProfile: activeProfile?.name || null,
  }));

  for (const [index, profile] of orderedProfiles.entries()) {
    const recentRuns = await prisma.benchmarkRun.findMany({
      where: { modelName: profile.name },
      orderBy: { createdAt: "desc" },
      take: 10,
    });
    if (recentRuns.some((run) => isComparableRun(run.optionsJson, profile.name, profile.modelPath))) {
      console.log(JSON.stringify({
        event: "model.skipped",
        index: index + 1,
        total: orderedProfiles.length,
        model: profile.name,
        reason: "comparable result already saved",
      }));
      continue;
    }

    console.log(JSON.stringify({
      event: "model.started",
      index: index + 1,
      total: orderedProfiles.length,
      model: profile.name,
    }));
    try {
      const result = await runConfiguredBenchmark({
        model: profile.name,
        modelPath: profile.modelPath,
        prompt: DEFAULT_BENCHMARK_PROMPT,
        maxOutputTokens: 2048,
        temperature: 0,
        repetitions: 2,
        warmup: false,
      });
      console.log(JSON.stringify({
        event: "model.completed",
        index: index + 1,
        total: orderedProfiles.length,
        model: profile.name,
        runId: result.runId,
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown benchmark failure";
      failures.push({ model: profile.name, error: message });
      console.error(JSON.stringify({
        event: "model.failed",
        index: index + 1,
        total: orderedProfiles.length,
        model: profile.name,
        error: message,
      }));
    }
  }

  console.log(JSON.stringify({
    event: failures.length ? "suite.completed_with_failures" : "suite.completed",
    models: orderedProfiles.length,
    failures,
  }));
  if (failures.length) process.exitCode = 1;
}

main()
  .catch((error) => {
    console.error(JSON.stringify({
      event: "suite.failed",
      error: error instanceof Error ? error.message : "Unknown suite failure",
    }));
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
