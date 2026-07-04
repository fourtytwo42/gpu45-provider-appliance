import { describe, expect, it } from "vitest";
import { classifyModelAsset, findModelCompanions } from "./model-assets";
import { modelProfileName } from "./model-catalog";
import type { ModelAsset } from "./types";

const asset = (name: string): ModelAsset => ({ name, path: `/models/repo/main/${name}`, sizeBytes: 1, multimodal: false, active: false });

describe("model asset companions", () => {
  it("distinguishes primary, MTP, and projector GGUF files", () => {
    expect(classifyModelAsset("Gemma-Q4_K_M.gguf")).toBe("model");
    expect(classifyModelAsset("mtp-gemma-31B.gguf")).toBe("mtp");
    expect(classifyModelAsset("M-SHQ8-MTP-OptA-Q5_K_M.gguf")).toBe("model");
    expect(classifyModelAsset("mmproj-Gemma-BF16.gguf")).toBe("projector");
  });

  it("binds companions only from the primary model directory", () => {
    const models = [asset("Gemma-Q4_K_M.gguf"), asset("mtp-gemma-31B.gguf"), asset("mmproj-Gemma-BF16.gguf")];
    expect(findModelCompanions(models, models[0].path)).toEqual({
      modelDraftPath: models[1].path,
      mmprojPath: models[2].path,
    });
  });

  it("uses stable unique launch profile names per model path", () => {
    const first = modelProfileName("/models/a/Gemma-Q4_K_M.gguf");
    const second = modelProfileName("/models/b/Gemma-Q4_K_M.gguf");
    expect(first).toMatch(/^gpu45-gemma-q4-k-m-[a-f0-9]{8}$/);
    expect(second).toMatch(/^gpu45-gemma-q4-k-m-[a-f0-9]{8}$/);
    expect(first).not.toBe(second);
  });
});
