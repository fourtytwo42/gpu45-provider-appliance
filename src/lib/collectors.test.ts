import { describe, expect, it } from "vitest";
import { isFanControllerHwmonName } from "./collectors";

describe("collectors", () => {
  it("matches the fan controller hwmon name even with trailing whitespace", () => {
    expect(isFanControllerHwmonName("nct6687\n")).toBe(true);
    expect(isFanControllerHwmonName(" NCT6687 ")).toBe(true);
  });

  it("rejects unrelated hwmon names", () => {
    expect(isFanControllerHwmonName("it8686")).toBe(false);
    expect(isFanControllerHwmonName(null)).toBe(false);
  });
});
