import { afterEach, describe, expect, it } from "vitest";
import { getApplianceVersion } from "./version";

const originalCommit = process.env.GPU45_RELEASE_COMMIT;
const originalReleasedAt = process.env.GPU45_RELEASED_AT;

afterEach(() => {
  process.env.GPU45_RELEASE_COMMIT = originalCommit;
  process.env.GPU45_RELEASED_AT = originalReleasedAt;
});

describe("getApplianceVersion", () => {
  it("reports release metadata from the environment", () => {
    process.env.GPU45_RELEASE_COMMIT = "abcdef1234567890";
    process.env.GPU45_RELEASED_AT = "2026-07-09T22:00:00Z";

    expect(getApplianceVersion()).toEqual({
      version: "0.1.0",
      commit: "abcdef1234567890",
      releasedAt: "2026-07-09T22:00:00Z",
    });
  });
});
