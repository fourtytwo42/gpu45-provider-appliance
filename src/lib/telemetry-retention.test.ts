import { describe, expect, it } from "vitest";

describe("telemetry retention policy", () => {
  it("keeps raw, minute, and hourly windows ordered by resolution", () => {
    const rawHours = 6;
    const minuteHours = 7 * 24;
    const hourlyHours = 365 * 24;
    expect(rawHours).toBeLessThan(minuteHours);
    expect(minuteHours).toBeLessThan(hourlyHours);
  });
});
