import { afterEach, describe, expect, it, vi } from "vitest";
import { searchHuggingFaceModels } from "./huggingface";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("huggingface search", () => {
  it("prefers lmstudio-compatible gguf results", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => [
          {
            modelId: "org/plain-model",
            tags: ["gguf"],
            siblings: [{ rfilename: "model.gguf" }],
            likes: 5,
            downloads: 10,
          },
          {
            modelId: "lmstudio-community/Qwen3.6-27B-Instruct-GGUF",
            tags: ["lmstudio", "gguf", "multimodal"],
            siblings: [{ rfilename: "model.gguf" }, { rfilename: "mmproj.gguf" }],
            likes: 50,
            downloads: 100,
          },
        ],
      })) as unknown as typeof fetch,
    );

    const results = await searchHuggingFaceModels("qwen");
    expect(results[0]?.repoId).toContain("lmstudio-community");
    expect(results[0]?.recommended).toBe(true);
    expect(results[0]?.reason).toContain("lmstudio");
  });
});

