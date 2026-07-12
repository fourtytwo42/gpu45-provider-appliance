import { describe, expect, it } from "vitest";
import { prometheusLabel, recordRequest, requestMetrics } from "./observability";

describe("observability", () => {
  it("escapes Prometheus label text", () => {
    expect(prometheusLabel('a"b\\c\nd')).toBe('a\\"b\\\\c\\nd');
  });

  it("accumulates request duration and failures", () => {
    recordRequest("/test", 10, true);
    recordRequest("/test", 20, false);
    expect(requestMetrics()).toContainEqual({ route: "/test", count: 2, failures: 1, durationMs: 30, maxDurationMs: 20 });
  });
});
