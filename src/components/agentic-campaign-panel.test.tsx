import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgenticCampaignDetail, AgenticModel } from "@/lib/agentic-benchmarks";
import { AgenticCampaignPanel } from "./agentic-campaign-panel";

const models: AgenticModel[] = [{
  name: "qwen-q5",
  description: "Qwen3.6 27B Q5",
  profileHash: "profile-hash",
}];

const detail: AgenticCampaignDetail = {
  campaign: {
    id: "campaign-1",
    name: "Common agentic campaign",
    preset: "common",
    status: "completed",
    phase: "common",
    created_at: "2026-07-17T00:00:00Z",
    updated_at: "2026-07-17T01:00:00Z",
  },
  runs: [{
    id: "run-1",
    profile_name: "qwen-q5",
    suite_id: "bfcl-v4-local",
    status: "completed",
    expected_tasks: 4,
    completed_tasks: 4,
    passed_tasks: 3,
    failed_tasks: 1,
    score: 0.75,
  }],
  ranking: [{ profileName: "qwen-q5", compositeScore: 0.75, invalidOutputRate: 0 }],
  events: [],
  artifacts: [],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AgenticCampaignPanel", () => {
  it("separates capability results from the quality-gated efficiency panel", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        sourceCampaignId: "campaign-1",
        campaignId: null,
        status: "not_started",
        rows: [],
        tie: false,
        confirmationRecommended: false,
        referenceCampaignId: null,
        referenceStatus: "not_started",
        referenceRows: [],
      }),
    }));

    render(<AgenticCampaignPanel
      detail={detail}
      models={models}
      suiteById={new Map()}
      busy={false}
      onAction={vi.fn()}
      onClose={vi.fn()}
    />);

    expect(screen.getByRole("tab", { name: "Capability" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Qwen3.6 27B Q5")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Efficiency" }));

    expect(await screen.findByText("Finalist panel has not started")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Codex baseline" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Run finalist panel" })).toBeEnabled();
  });

  it("shows the Codex agent-system baseline without assigning local GPU energy", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        sourceCampaignId: "campaign-1",
        campaignId: "efficiency-1",
        status: "completed",
        rows: [],
        tie: false,
        confirmationRecommended: false,
        referenceCampaignId: "reference-1",
        referenceStatus: "completed",
        referenceRows: [{
          profileName: "reference-codex-gpt-5.6-sol-medium",
          displayName: "Codex GPT-5.6 Sol Medium",
          systemType: "agent-system-reference",
          expectedTasks: 11,
          completedTasks: 11,
          successes: 8,
          promptTokens: 1000,
          completionTokens: 400,
          totalTokens: 1400,
          activeInferenceMs: 8000,
          wallDurationMs: 9000,
          responseCalls: 11,
          toolCalls: 8,
          invalidCalls: 0,
          panelScore: 0.75,
          timePerSolveMs: 1000,
          tokensPerSolve: 175,
          measurementComplete: true,
          energyAvailable: false,
        }],
      }),
    }));

    render(<AgenticCampaignPanel detail={detail} models={models} suiteById={new Map()} busy={false} onAction={vi.fn()} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: "Efficiency" }));

    expect(await screen.findByText("Codex GPT-5.6 Sol Medium")).toBeInTheDocument();
    expect(screen.getByText("Cloud n/a")).toBeInTheDocument();
  });
});
