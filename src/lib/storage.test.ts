import { describe, expect, it } from "vitest";
import { withinManagedStorage } from "./storage";

describe("withinManagedStorage", () => {
  it("allows managed assets but never direct trash selections", () => {
    expect(withinManagedStorage("/models/huggingface/model.gguf")).toBe(true);
    expect(withinManagedStorage("/opt/ltx2")).toBe(true);
    expect(withinManagedStorage("/models/.trash/operation/model.gguf")).toBe(false);
  });

  it("rejects paths outside explicitly managed roots", () => {
    expect(withinManagedStorage("/etc/gpu45/provider-profile.json")).toBe(false);
    expect(withinManagedStorage("/opt/qwen3-tts")).toBe(false);
  });
});
