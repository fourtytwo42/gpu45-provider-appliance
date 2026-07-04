import { describe, expect, it } from "vitest";
import { DEFAULT_BENCHMARK_PROMPT, benchmarkOptionsSchema } from "./benchmarks";

describe("benchmarkOptionsSchema", () => {
  it("uses the appliance benchmark defaults without manual prompt controls", () => {
    const options = benchmarkOptionsSchema.parse({
      model: "qwen",
      modelPath: "/models/qwen.gguf",
    });
    expect(options).toMatchObject({
      model: "qwen",
      modelPath: "/models/qwen.gguf",
      prompt: DEFAULT_BENCHMARK_PROMPT,
      maxOutputTokens: 2048,
      temperature: 0,
      repetitions: 2,
      warmup: false,
    });
  });

  it("still accepts explicit controls for internal callers", () => {
    const options = benchmarkOptionsSchema.parse({
      model: "qwen",
      prompt: "hello",
      maxOutputTokens: "512",
      temperature: "0.2",
      repetitions: "3",
      warmup: true,
    });
    expect(options).toMatchObject({ maxOutputTokens: 512, temperature: 0.2, repetitions: 3, warmup: true });
  });

  it("rejects unsafe benchmark sizes", () => {
    expect(() => benchmarkOptionsSchema.parse({ model: "qwen", prompt: "hello", maxOutputTokens: 10000 })).toThrow();
  });
});
