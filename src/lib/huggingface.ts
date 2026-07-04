import { getConfig } from "./config";

export type HuggingFaceSearchResult = {
  repoId: string;
  name: string;
  tags: string[];
  likes: number;
  downloads: number;
  score: number;
  recommended: boolean;
  reason: string;
  ggufFiles: string[];
  multimodal: boolean;
};

function scoreResult(result: {
  modelId: string;
  tags?: string[];
  siblings?: Array<{ rfilename: string }>;
  likes?: number;
  downloads?: number;
}): HuggingFaceSearchResult {
  const repoId = result.modelId;
  const tags = (result.tags ?? []).map((tag) => tag.toLowerCase());
  const files = (result.siblings ?? []).map((item) => item.rfilename).filter(Boolean);
  const ggufFiles = files.filter((file) => file.toLowerCase().endsWith(".gguf"));
  const multimodal = tags.includes("multimodal") || ggufFiles.some((file) => file.toLowerCase().includes("mmproj") || file.toLowerCase().includes("vl"));

  let score = 0;
  const reasons: string[] = [];
  if (repoId.toLowerCase().includes("lmstudio-community") || repoId.toLowerCase().includes("/lmstudio")) {
    score += 100;
    reasons.push("lmstudio-compatible source");
  }
  if (tags.includes("gguf") || ggufFiles.length > 0) {
    score += 70;
    reasons.push("GGUF files available");
  }
  if (tags.includes("lmstudio")) {
    score += 60;
    reasons.push("lmstudio tag");
  }
  if (multimodal) {
    score += 25;
    reasons.push("multimodal support");
  }
  if (tags.some((tag) => tag.includes("qwen"))) {
    score += 10;
  }

  return {
    repoId,
    name: repoId.split("/").slice(-1)[0] ?? repoId,
    tags,
    likes: result.likes ?? 0,
    downloads: result.downloads ?? 0,
    score,
    recommended: score >= 120,
    reason: reasons.join(", ") || "generic match",
    ggufFiles,
    multimodal,
  };
}

export async function searchHuggingFaceModels(query: string): Promise<HuggingFaceSearchResult[]> {
  const trimmed = query.trim();
  if (!trimmed) return [];

  const response = await fetch(`https://huggingface.co/api/models?search=${encodeURIComponent(trimmed)}&limit=20&full=true`, {
    headers: getConfig().hfToken ? { Authorization: `Bearer ${getConfig().hfToken}` } : undefined,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`huggingface search failed: ${response.status}`);
  }
  const results = (await response.json()) as Array<{
    modelId: string;
    tags?: string[];
    siblings?: Array<{ rfilename: string }>;
    likes?: number;
    downloads?: number;
  }>;
  return results
    .map(scoreResult)
    .sort((left, right) => right.score - left.score || right.downloads - left.downloads || right.likes - left.likes)
    .slice(0, 12);
}

