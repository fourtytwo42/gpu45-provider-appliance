import { describe, expect, it } from "vitest";
import type { AgenticLatestResult, AgenticModel } from "./agentic-benchmarks";
import { buildUnifiedBenchmarkRows } from "./benchmark-results";
import type { BenchmarkRun } from "./types";

const models: AgenticModel[] = [
  { name: "model-a-q5", description: "Model A Q5", modelPath: "/models/model-a-q5.gguf", profileHash: "a" },
  { name: "model-b-q6", description: "Model B Q6", modelPath: "/models/model-b-q6.gguf", profileHash: "b" },
];

function throughput(modelName: string, createdAt: string, speed: number, modelPath?: string): BenchmarkRun {
  return {
    id: `${modelName}-${createdAt}`,
    modelName,
    prompt: "fixed",
    totalTokens: 100,
    promptTokens: 20,
    completionTokens: 80,
    promptTokensPerSecond: 100,
    generationTokensPerSecond: speed,
    durationMs: 1000,
    optionsJson: modelPath ? JSON.stringify({ modelPath }) : "{}",
    createdAt,
  };
}

function agentic(profileName: string, score: number): AgenticLatestResult {
  return {
    profileName,
    campaignId: `${profileName}-campaign`,
    status: "completed",
    createdAt: "2026-07-20T00:00:00Z",
    updatedAt: "2026-07-20T01:00:00Z",
    completedAt: "2026-07-20T01:00:00Z",
    expectedTasks: 67,
    completedTasks: 67,
    passedTasks: 50,
    failedTasks: 17,
    invalidOutputRate: 0,
    compositeScore: score,
    suites: {},
  };
}

describe("buildUnifiedBenchmarkRows", () => {
  it("combines the newest throughput and agentic results into one model row", () => {
    const rows = buildUnifiedBenchmarkRows(models, [
      throughput("model-a-q5", "2026-07-18T00:00:00Z", 40),
      throughput("model-a-q5", "2026-07-19T00:00:00Z", 42),
    ], [agentic("model-a-q5", 0.72)]);

    expect(rows[0]).toMatchObject({
      profileName: "model-a-q5",
      displayName: "Model A Q5",
      agentic: { compositeScore: 0.72 },
      throughput: { generationTokensPerSecond: 42 },
    });
    expect(rows.find((row) => row.profileName === "model-b-q6")).toMatchObject({
      agentic: null,
      throughput: null,
    });
  });

  it("matches older throughput rows by the saved model path", () => {
    const rows = buildUnifiedBenchmarkRows(models, [
      throughput("provider-generated-name", "2026-07-19T00:00:00Z", 30, "/models/model-b-q6.gguf"),
    ], []);

    expect(rows.find((row) => row.profileName === "model-b-q6")?.throughput?.modelName).toBe("provider-generated-name");
  });

  it("keeps unmatched throughput history visible and ranks scored models first", () => {
    const rows = buildUnifiedBenchmarkRows(models, [
      throughput("legacy-model", "2026-07-19T00:00:00Z", 100),
    ], [agentic("model-b-q6", 0.6)]);

    expect(rows[0].profileName).toBe("model-b-q6");
    expect(rows.some((row) => row.profileName === "legacy-model")).toBe(true);
  });

  it("keeps an unmatched agent-system reference as a scored table row", () => {
    const reference = {
      ...agentic("reference-codex-gpt-5.6-sol-medium", 0.625),
      displayName: "Codex GPT-5.6 Sol Medium",
      systemType: "agent-system-reference" as const,
    };

    const rows = buildUnifiedBenchmarkRows(models, [], [reference]);
    const row = rows.find((item) => item.profileName === reference.profileName);

    expect(row).toMatchObject({
      displayName: "Codex GPT-5.6 Sol Medium",
      agentic: { compositeScore: 0.625, systemType: "agent-system-reference" },
      throughput: null,
    });
  });
});
