import { describe, expect, it } from "vitest";
import { WHISPER_MODELS, whisperOutlineUrl, whisperTranscriptUrl } from "./whisper";

describe("whisper helpers", () => {
  it("exposes the expected selectable model sizes", () => {
    expect(WHISPER_MODELS).toEqual(["tiny", "base", "small", "medium", "large-v3", "turbo"]);
  });

  it("builds transcript download URLs with encoded ids", () => {
    expect(whisperTranscriptUrl("job 1")).toBe("/api/whisper/output?id=job%201");
    expect(whisperOutlineUrl("job 1")).toBe("/api/whisper/output?id=job%201&asset=outline");
  });
});
