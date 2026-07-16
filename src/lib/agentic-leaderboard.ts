export type AgenticRunSummary = {
  profile_name: string;
  suite_id: string;
  status: string;
  expected_tasks?: number | null;
  completed_tasks?: number | null;
  passed_tasks?: number | null;
  failed_tasks?: number | null;
  score?: number | null;
  invalid_output_rate?: number | null;
};

export type AgenticRankingSummary = {
  profileName: string;
  scores?: Record<string, number | null>;
  compositeScore?: number | null;
  invalidOutputRate?: number | null;
};

export type AgenticLeaderboardRow = {
  profileName: string;
  rank: number | null;
  completedTasks: number;
  expectedTasks: number;
  passedTasks: number;
  failedTasks: number;
  invalidOutputRate: number;
  compositeScore: number | null;
  suites: Record<string, AgenticRunSummary>;
};

export function buildAgenticLeaderboard(
  runs: AgenticRunSummary[],
  ranking: AgenticRankingSummary[],
): AgenticLeaderboardRow[] {
  const rankingByProfile = new Map(ranking.map((row, index) => [row.profileName, { ...row, rank: index + 1 }]));
  const rows = new Map<string, AgenticLeaderboardRow>();

  for (const run of runs) {
    const rankingRow = rankingByProfile.get(run.profile_name);
    const row = rows.get(run.profile_name) || {
      profileName: run.profile_name,
      rank: rankingRow?.compositeScore == null ? null : rankingRow.rank,
      completedTasks: 0,
      expectedTasks: 0,
      passedTasks: 0,
      failedTasks: 0,
      invalidOutputRate: Number(rankingRow?.invalidOutputRate || 0),
      compositeScore: rankingRow?.compositeScore ?? null,
      suites: {},
    };
    row.completedTasks += Number(run.completed_tasks || 0);
    row.expectedTasks += Number(run.expected_tasks || 0);
    row.passedTasks += Number(run.passed_tasks || 0);
    row.failedTasks += Number(run.failed_tasks || 0);
    row.suites[run.suite_id] = run;
    rows.set(run.profile_name, row);
  }

  return [...rows.values()].sort((left, right) => {
    if (left.rank != null && right.rank != null) return left.rank - right.rank;
    if (left.rank != null) return -1;
    if (right.rank != null) return 1;
    if (left.completedTasks !== right.completedTasks) return right.completedTasks - left.completedTasks;
    return left.profileName.localeCompare(right.profileName);
  });
}
