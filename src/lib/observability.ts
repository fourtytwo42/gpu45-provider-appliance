type RequestStats = { count: number; failures: number; durationMs: number; maxDurationMs: number };

const requests = new Map<string, RequestStats>();

export function recordRequest(route: string, durationMs: number, ok: boolean): void {
  const current = requests.get(route) ?? { count: 0, failures: 0, durationMs: 0, maxDurationMs: 0 };
  current.count += 1;
  current.failures += ok ? 0 : 1;
  current.durationMs += durationMs;
  current.maxDurationMs = Math.max(current.maxDurationMs, durationMs);
  requests.set(route, current);
}

export function requestMetrics(): Array<{ route: string } & RequestStats> {
  return [...requests.entries()].map(([route, stats]) => ({ route, ...stats }));
}

export function prometheusLabel(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll("\n", "\\n").replaceAll('"', '\\"');
}
