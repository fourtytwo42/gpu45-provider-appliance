import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgenticLatestResult, AgenticModel } from "@/lib/agentic-benchmarks";
import type { BenchmarkRun } from "@/lib/types";
import { UnifiedBenchmarkConsole } from "./unified-benchmark-console";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

const models: AgenticModel[] = [{
  name: "qwen-q5",
  description: "Qwen Q5",
  modelPath: "/models/qwen-q5.gguf",
  profileHash: "hash",
}];

const agenticResults: AgenticLatestResult[] = [{
  profileName: "qwen-q5",
  campaignId: "campaign",
  status: "completed",
  createdAt: "2026-07-20T00:00:00Z",
  updatedAt: "2026-07-20T01:00:00Z",
  completedAt: "2026-07-20T01:00:00Z",
  expectedTasks: 70,
  completedTasks: 70,
  passedTasks: 50,
  failedTasks: 17,
  invalidOutputRate: 0.01,
  compositeScore: 0.75,
  suites: {
    "bfcl-v4-local": { status: "completed", score: 0.8, expectedTasks: 36, completedTasks: 36, passedTasks: 29, failedTasks: 7 },
  },
}];

const runs: BenchmarkRun[] = [{
  id: "run",
  modelName: "qwen-q5",
  prompt: "fixed",
  totalTokens: 100,
  promptTokens: 20,
  completionTokens: 80,
  promptTokensPerSecond: 120,
  generationTokensPerSecond: 35,
  durationMs: 2000,
  createdAt: "2026-07-20T02:00:00Z",
}];

afterEach(() => {
  cleanup();
  refresh.mockReset();
  vi.unstubAllGlobals();
});

describe("UnifiedBenchmarkConsole", () => {
  it("shows capability and throughput in the same model row", () => {
    render(<UnifiedBenchmarkConsole initialRuns={runs} agenticModels={models} agenticResults={agenticResults} />);

    const row = screen.getByText("qwen-q5").closest("tr");
    expect(row).toHaveTextContent("75.0%");
    expect(row).toHaveTextContent("80.0%");
    expect(row).toHaveTextContent("120.0");
    expect(row).toHaveTextContent("35.0");
    expect(screen.queryByText("Campaigns")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });

  it("labels Codex interaction throughput as estimated", () => {
    const reference: AgenticLatestResult = {
      ...agenticResults[0],
      profileName: "reference-codex",
      displayName: "Codex GPT-5.6 Sol Medium",
      systemType: "agent-system-reference",
      estimatedPromptTokensPerSecond: 1527.1,
      estimatedOutputTokensPerSecond: 24.83,
      interactionDurationMs: 1_074_450,
    };

    render(<UnifiedBenchmarkConsole initialRuns={[]} agenticModels={[]} agenticResults={[reference]} />);

    const row = screen.getByText("Codex GPT-5.6 Sol Medium").closest("tr");
    expect(row).toHaveTextContent("~1527.1");
    expect(row).toHaveTextContent("~24.8");
    expect(row).toHaveTextContent("~17m 54s");
    expect(row).toHaveTextContent("Cloud n/a");
  });

  it("starts every model with the fixed throughput recipe", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 202,
      json: async () => ({
        job: {
          id: "job",
          status: "running",
          model: "qwen-q5",
          activeRun: 1,
          totalRuns: 2,
          startedAt: "2026-07-20T00:00:00Z",
          updatedAt: "2026-07-20T00:00:00Z",
          message: "Running",
          samples: [],
          partialRuns: [],
        },
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<UnifiedBenchmarkConsole initialRuns={[]} agenticModels={models} agenticResults={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Run full benchmark" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toMatchObject({
      model: "qwen-q5",
      modelPath: "/models/qwen-q5.gguf",
      repetitions: 2,
      maxOutputTokens: 2048,
      temperature: 0,
    });
  });
});
