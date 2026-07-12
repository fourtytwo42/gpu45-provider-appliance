import { describe, expect, it } from "vitest";
import { derivePersistedProviderStatus } from "./operational-state";
import type { ResourceState } from "./resource-manager";

function resources(overrides: Partial<ResourceState> = {}): ResourceState {
  return {
    status: "ready",
    owner: null,
    queue: [],
    suspended: [],
    vram: { usedBytes: 0, totalBytes: 32, freeBytes: 32 },
    recovery: { reclaimedLeases: 0, lastEvent: null },
    transition: null,
    services: { llm: "inactive" },
    workers: {},
    ...overrides,
  };
}

describe("derivePersistedProviderStatus", () => {
  it("treats an intentionally stopped LLM as healthy on-demand state", () => {
    expect(derivePersistedProviderStatus(resources(), "ready", 0)).toBe("unloaded");
  });

  it("uses the resource transition before stale persisted state", () => {
    expect(derivePersistedProviderStatus(resources({ transition: { status: "restoring", startedAt: "now" } }), "unloaded", 0)).toBe("restoring");
  });

  it("reports active request load from an active LLM", () => {
    expect(derivePersistedProviderStatus(resources({ services: { llm: "active" } }), "ready", 2)).toBe("busy");
  });
});
