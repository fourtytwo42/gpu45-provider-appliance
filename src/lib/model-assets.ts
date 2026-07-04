import type { ModelAsset } from "./types";

export type ModelAssetRole = "model" | "mtp" | "projector";

export function classifyModelAsset(name: string): ModelAssetRole {
  const normalized = name.replaceAll("\\", "/").split("/").at(-1)?.toLowerCase() ?? name.toLowerCase();
  if (normalized.includes("mmproj")) return "projector";
  if (/^(mtp|draft)([-_.]|$)/i.test(normalized)) return "mtp";
  return "model";
}

export function findModelCompanions(models: ModelAsset[], modelPath: string): { modelDraftPath: string | null; mmprojPath: string | null } {
  const directory = modelPath.replaceAll("\\", "/").split("/").slice(0, -1).join("/");
  const siblings = models.filter((asset) => asset.path.replaceAll("\\", "/").split("/").slice(0, -1).join("/") === directory && asset.path !== modelPath);
  return {
    modelDraftPath: siblings.find((asset) => classifyModelAsset(asset.name) === "mtp")?.path ?? null,
    mmprojPath: siblings.find((asset) => classifyModelAsset(asset.name) === "projector")?.path ?? null,
  };
}
