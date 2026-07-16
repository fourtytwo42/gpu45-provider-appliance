import { describe, expect, it } from "vitest";
import { buildAgenticLeaderboard } from "./agentic-leaderboard";

describe("buildAgenticLeaderboard", () => {
  it("combines suite runs into comparable model rows", () => {
    const rows = buildAgenticLeaderboard([
      { profile_name: "model-a", suite_id: "bfcl", status: "completed", expected_tasks: 10, completed_tasks: 10, passed_tasks: 8, failed_tasks: 2, score: 0.8 },
      { profile_name: "model-a", suite_id: "tau", status: "running", expected_tasks: 20, completed_tasks: 5, passed_tasks: 3, failed_tasks: 2, score: 0.6 },
      { profile_name: "model-b", suite_id: "bfcl", status: "queued", expected_tasks: 10 },
    ], [{ profileName: "model-a", compositeScore: 0.72, invalidOutputRate: 0.1 }]);

    expect(rows[0]).toMatchObject({
      profileName: "model-a", rank: 1, expectedTasks: 30, completedTasks: 15,
      passedTasks: 11, failedTasks: 4, compositeScore: 0.72, invalidOutputRate: 0.1,
    });
    expect(rows[0].suites.tau.score).toBe(0.6);
    expect(rows[1]).toMatchObject({ profileName: "model-b", rank: null, expectedTasks: 10, completedTasks: 0 });
  });

  it("does not assign a final rank until a composite score exists", () => {
    const rows = buildAgenticLeaderboard([
      { profile_name: "model-a", suite_id: "bfcl", status: "running", expected_tasks: 10, completed_tasks: 3, score: 0.66 },
    ], [{ profileName: "model-a", compositeScore: null }]);
    expect(rows[0].rank).toBeNull();
  });
});
