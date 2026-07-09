import { describe, expect, it } from "vitest";
import { normalizeStatus } from "./jobs";

describe("normalizeStatus", () => {
  it.each([
    ["ready", "completed"],
    ["complete", "completed"],
    ["training", "running"],
    ["paused", "paused"],
    ["something-new", "unknown"],
  ])("maps %s to %s", (input, expected) => {
    expect(normalizeStatus(input)).toBe(expected);
  });
});
