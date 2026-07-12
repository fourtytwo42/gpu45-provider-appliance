import { describe, expect, it } from "vitest";
import { normalizeStatus, paginateItems } from "./jobs";

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

describe("paginateItems", () => {
  it("returns stable bounded pages and a continuation cursor", () => {
    expect(paginateItems([0, 1, 2, 3, 4], 1, 2)).toEqual({ items: [1, 2], nextCursor: 3, total: 5 });
    expect(paginateItems([0, 1, 2], 2, 500)).toEqual({ items: [2], nextCursor: null, total: 3 });
  });

  it("normalizes invalid pagination values", () => {
    expect(paginateItems(["a", "b"], Number.NaN, 0)).toEqual({ items: ["a"], nextCursor: 1, total: 2 });
  });
});
