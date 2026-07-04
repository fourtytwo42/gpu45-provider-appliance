import { describe, expect, it } from "vitest";
import { isLogSource } from "./logs";

describe("isLogSource", () => {
  it("accepts known appliance services", () => {
    expect(isLogSource("provider")).toBe(true);
    expect(isLogSource("worker")).toBe(true);
  });

  it("rejects arbitrary journal units", () => {
    expect(isLogSource("ssh.service")).toBe(false);
  });
});
