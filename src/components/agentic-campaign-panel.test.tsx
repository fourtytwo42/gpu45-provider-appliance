import { fireEvent, render, screen } from "@testing-library/react";
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
    expect(screen.getByRole("button", { name: "Run finalist panel" })).toBeEnabled();
  });
});
