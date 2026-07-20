import { describe, expect, it } from "vitest";
import { musicOutputUrl } from "./music";

describe("music output URLs", () => {
  it("encodes job and asset names", () => {
    expect(musicOutputUrl("job/one", "lead vocal")).toBe("/api/music/jobs/job%2Fone/output?asset=lead%20vocal");
  });
});
