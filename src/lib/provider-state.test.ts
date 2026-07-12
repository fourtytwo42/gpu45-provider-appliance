import { describe, expect, it } from "vitest";
import { deriveProviderStatus } from "./provider-state";

const base = {
  proxyReady: true,
  backendReady: false,
  processStatus: "inactive" as const,
  activeRequests: 0,
  resourceOwner: null,
  transition: null,
};

describe("deriveProviderStatus", () => {
  it("treats an intentionally stopped backend as unloaded", () => {
    expect(deriveProviderStatus(base)).toBe("unloaded");
  });

  it("reports ready and busy from a live backend", () => {
    expect(deriveProviderStatus({ ...base, backendReady: true })).toBe("ready");
    expect(deriveProviderStatus({ ...base, backendReady: true, activeRequests: 1 })).toBe("busy");
  });

  it("preserves resource transitions", () => {
    expect(deriveProviderStatus({ ...base, transition: "restoring" })).toBe("restoring");
    expect(deriveProviderStatus({ ...base, transition: "releasing" })).toBe("releasing");
    expect(deriveProviderStatus({ ...base, transition: "starting" })).toBe("starting");
  });

  it("only reports failed for a failed proxy or process", () => {
    expect(deriveProviderStatus({ ...base, proxyReady: false })).toBe("failed");
    expect(deriveProviderStatus({ ...base, processStatus: "failed" })).toBe("failed");
  });
});
