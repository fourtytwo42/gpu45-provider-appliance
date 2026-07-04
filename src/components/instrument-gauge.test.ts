import { describe, expect, it } from "vitest";
import { normalizeGaugeValue } from "./instrument-gauge";

describe("normalizeGaugeValue", () => {
  it("keeps values inside the instrument scale", () => {
    expect(normalizeGaugeValue(72, 100)).toBe(72);
  });

  it("clamps unavailable and out-of-range readings", () => {
    expect(normalizeGaugeValue(null, 100)).toBe(0);
    expect(normalizeGaugeValue(-4, 100)).toBe(0);
    expect(normalizeGaugeValue(140, 100)).toBe(100);
  });
});
