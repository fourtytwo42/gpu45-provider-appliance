import { classifyModelAsset } from "./model-assets";
import type { BenchmarkRun, ModelAsset } from "./types";

export type ModelCapability = {
  name: string;
  alias?: string | null;
  active: boolean;
  served: boolean;
  text: boolean;
  vision: boolean;
  toolCalling: "expected" | "limited" | "unknown";
  reasoning: "on" | "optional" | "unknown";
  mtp: boolean;
  maxContext: number;
  codex: "ready" | "check" | "risky";
  bestPromptTps?: number | null;
  bestDecodeTps?: number | null;
  knownIssue?: string | null;
  configured: boolean;
  detected: boolean;
  verified: boolean;
  lastVerifiedAt?: string | null;
};

function modelKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function hasVision(model: ModelAsset): boolean {
  const name = model.name.toLowerCase();
  return Boolean(model.projectorPath || model.multimodal || /vision|vl|mmproj|qwen2\.5-vl|llava/.test(name));
}

function knownIssue(model: ModelAsset): string | null {
  const name = model.name.toLowerCase();
  if (model.launchProfile?.backend === "vulkan") return "Fast decode profile. Load-aware fan boost is required; uncached prompt processing is slightly slower than the ROCm profile.";
  if (name.includes("gemma")) return "Watch tool-calling behavior in Codex; prior Gemma runs talked about actions without executing tools.";
  if (name.includes("qwythos")) return "Use tested context settings; prior long-context runs hit stream completion issues.";
  return null;
}

export function deriveModelCapabilities(models: ModelAsset[], benchmarks: BenchmarkRun[]): ModelCapability[] {
  const primary = models.filter((model) => classifyModelAsset(model.name) === "model");
  return primary.map((model) => {
    const name = model.name;
    const lower = name.toLowerCase();
    const benchMatches = benchmarks.filter((run) => modelKey(run.modelName).includes(modelKey(name).slice(0, 24)) || modelKey(name).includes(modelKey(run.modelName).slice(0, 24)));
    const bestPromptTps = benchMatches.length ? Math.max(...benchMatches.map((run) => run.promptTokensPerSecond)) : null;
    const bestDecodeTps = benchMatches.length ? Math.max(...benchMatches.map((run) => run.generationTokensPerSecond)) : null;
    const latestBenchmark = benchMatches.map((run) => run.createdAt).sort((a, b) => b.localeCompare(a))[0];
    const mtp = Boolean(model.draftPath || model.launchProfile?.specType === "draft-mtp" || /mtp/.test(`${lower} ${model.path.toLowerCase()}`));
    const maxContext = model.launchProfile?.ctxSize ?? 262144;
    const issue = knownIssue(model);
    const toolCalling: ModelCapability["toolCalling"] = lower.includes("gemma") ? "limited" : model.served ? "expected" : "unknown";
    const reasoning: ModelCapability["reasoning"] = lower.includes("ornith") ? "on" : "optional";
    const codex: ModelCapability["codex"] = model.served && !issue ? "ready" : model.served ? "check" : "risky";
    return {
      name,
      alias: model.servedAlias,
      active: model.active,
      served: Boolean(model.served),
      text: true,
      vision: hasVision(model),
      toolCalling,
      reasoning,
      mtp,
      maxContext,
      codex,
      bestPromptTps,
      bestDecodeTps,
      knownIssue: issue,
      configured: Boolean(model.launchProfile),
      detected: Boolean(model.served || model.active),
      verified: benchMatches.length > 0,
      lastVerifiedAt: latestBenchmark ?? null,
    };
  }).sort((a, b) => Number(b.active) - Number(a.active) || Number(b.served) - Number(a.served) || a.name.localeCompare(b.name));
}
