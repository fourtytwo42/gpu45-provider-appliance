import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration, formatPercent } from "./format";

describe("format helpers", () => {
  it("formats bytes", () => {
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1024 ** 3)).toBe("1.0 GB");
  });

  it("formats durations", () => {
    expect(formatDuration(999)).toBe("999 ms");
    expect(formatDuration(1500)).toBe("1.5 s");
  });

  it("formats percent", () => {
    expect(formatPercent(12.34)).toBe("12%");
    expect(formatPercent(12.34, 1)).toBe("12.3%");
  });
});

