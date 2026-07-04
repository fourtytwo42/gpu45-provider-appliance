import { describe, expect, it } from "vitest";
import { imageOutputUrl } from "./images";

describe("image helpers", () => {
  it("builds image output URLs with encoded ids", () => {
    expect(imageOutputUrl("job 1")).toBe("/api/images/output?id=job%201");
  });
});
