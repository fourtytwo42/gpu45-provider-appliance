import { createHash } from "node:crypto";
import path from "node:path";
import { z } from "zod";
import { prisma } from "./db";
import { classifyModelAsset } from "./model-assets";
import type { LaunchProfile, ModelAsset } from "./types";

export function modelAlias(name: string, modelPath: string): string {
  const base = path.basename(name, path.extname(name)).replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-|-$/g, "").slice(0, 100) || "model";
  const suffix = createHash("sha1").update(modelPath).digest("hex").slice(0, 8);
  return `${base}-${suffix}`;
}

export function modelProfileName(modelPath: string): string {
  const base = path.basename(modelPath, path.extname(modelPath)).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 64) || "model";
  const suffix = createHash("sha1").update(modelPath).digest("hex").slice(0, 8);
  return `gpu45-${base}-${suffix}`;
}

const modelSettingsSchema = z.object({
  ctxSize: z.coerce.number().int().min(1024).max(262144).optional(),
  gpuLayers: z.string().min(1).max(24).optional(),
  batchSize: z.coerce.number().int().min(64).max(8192).optional(),
  uBatchSize: z.coerce.number().int().min(32).max(4096).optional(),
  cacheRamMiB: z.coerce.number().int().min(0).max(131072).optional(),
  cacheTypeK: z.string().min(2).max(32).optional(),
  cacheTypeV: z.string().min(2).max(32).optional(),
  cacheReuse: z.coerce.number().int().min(0).max(262144).optional(),
  specType: z.enum(["none", "draft-mtp"]).optional(),
  specDraftNMax: z.coerce.number().int().min(1).max(16).optional(),
  flashAttention: z.enum(["on", "off", "auto"]).optional(),
  imageMinTokens: z.coerce.number().int().min(0).max(8192).optional(),
  metrics: z.coerce.boolean().optional(),
  jinja: z.coerce.boolean().optional(),
});

export type ModelSettingsInput = z.infer<typeof modelSettingsSchema>;

function serializeLaunchProfile(profile: {
  name: string;
  description: string | null;
  modelPath: string;
  mmprojPath: string | null;
  modelDraftPath: string | null;
  host: string;
  port: number;
  ctxSize: number;
  gpuLayers: string;
  batchSize: number;
  uBatchSize: number;
  cacheRamMiB: number;
  cacheTypeK: string;
  cacheTypeV: string;
  cacheReuse: number;
  specType: string;
  specDraftNMax: number;
  flashAttention: string;
  backend: string;
  serverBinary: string | null;
  runtimeLibraryPath: string | null;
  fanBoostOnBusy: boolean;
  imageMinTokens: number;
  metrics: boolean;
  jinja: boolean;
  active: boolean;
}): LaunchProfile {
  return {
    ...profile,
    backend: profile.backend === "vulkan" ? "vulkan" : "rocm",
  };
}

export async function syncModelCatalog(models: ModelAsset[]): Promise<ModelAsset[]> {
  const existing = await prisma.modelAsset.findMany();
  const byPath = new Map(existing.map((asset) => [asset.path, asset]));
  const activePrimary = models.find((model) => model.active && classifyModelAsset(model.name) === "model")?.path;

  for (const model of models) {
    const current = byPath.get(model.path);
    const primary = classifyModelAsset(model.name) === "model";
    await prisma.modelAsset.upsert({
      where: { path: model.path },
      create: {
        name: model.name,
        path: model.path,
        repo: model.repo ?? null,
        revision: model.revision ?? null,
        sizeBytes: BigInt(model.sizeBytes),
        multimodal: model.multimodal,
        projectorPath: model.projectorPath ?? null,
        draftPath: model.draftPath ?? null,
        active: model.active,
        served: primary,
        servedAlias: primary ? modelAlias(model.name, model.path) : null,
        defaultModel: model.path === activePrimary,
      },
      update: {
        name: model.name,
        repo: model.repo ?? current?.repo ?? null,
        revision: model.revision ?? current?.revision ?? null,
        sizeBytes: BigInt(model.sizeBytes),
        multimodal: model.multimodal,
        active: model.active,
        projectorPath: model.projectorPath ?? current?.projectorPath ?? null,
        draftPath: model.draftPath ?? current?.draftPath ?? null,
        served: primary ? current?.served ?? true : false,
        servedAlias: primary ? current?.servedAlias ?? modelAlias(model.name, model.path) : null,
      },
    });
  }
  if (activePrimary && !existing.some((asset) => asset.defaultModel)) {
    await prisma.modelAsset.updateMany({ where: { path: activePrimary }, data: { defaultModel: true } });
  }

  const modelPaths = models.map((model) => model.path);
  const [catalog, profiles] = await Promise.all([
    prisma.modelAsset.findMany({ where: { path: { in: modelPaths } } }),
    prisma.launchProfile.findMany({ where: { modelPath: { in: modelPaths } } }),
  ]);
  const settings = new Map(catalog.map((asset) => [asset.path, asset]));
  const profilesByPath = new Map(profiles.map((profile) => [profile.modelPath, serializeLaunchProfile(profile)]));
  return models.map((model) => {
    const asset = settings.get(model.path);
    return {
      ...model,
      served: asset?.served ?? false,
      servedAlias: asset?.servedAlias ?? null,
      defaultModel: asset?.defaultModel ?? false,
      projectorPath: asset?.projectorPath ?? model.projectorPath ?? null,
      draftPath: asset?.draftPath ?? model.draftPath ?? null,
      launchProfile: profilesByPath.get(model.path) ?? null,
    };
  });
}

export async function updateModelServing(modelPath: string, served?: boolean, defaultModel?: boolean): Promise<void> {
  const model = await prisma.modelAsset.findUnique({ where: { path: modelPath } });
  if (!model || classifyModelAsset(model.name) !== "model") throw new Error("Only primary models can be served.");
  await prisma.$transaction(async (tx) => {
    if (defaultModel) await tx.modelAsset.updateMany({ data: { defaultModel: false } });
    await tx.modelAsset.update({
      where: { path: modelPath },
      data: {
        ...(served === undefined ? {} : { served }),
        ...(defaultModel === undefined ? {} : { defaultModel }),
      },
    });
  });
}

export async function updateModelSettings(modelPath: string, input: unknown): Promise<LaunchProfile> {
  const settings = modelSettingsSchema.parse(input);
  const model = await prisma.modelAsset.findUnique({ where: { path: modelPath } });
  if (!model || classifyModelAsset(model.name) !== "model") throw new Error("Only primary models can have launch settings.");

  const activeProfile = await prisma.launchProfile.findFirst({ where: { active: true } });
  const existing = await prisma.launchProfile.findFirst({ where: { modelPath } });
  const name = existing?.name ?? modelProfileName(modelPath);
  const supportsMtp = Boolean(existing?.modelDraftPath ?? model.draftPath) || path.dirname(modelPath).toLowerCase().includes("mtp");
  const profile: LaunchProfile = {
    name,
    description: `${model.name} launch settings`,
    modelPath,
    mmprojPath: existing?.mmprojPath ?? model.projectorPath ?? null,
    modelDraftPath: existing?.modelDraftPath ?? model.draftPath ?? null,
    host: existing?.host ?? activeProfile?.host ?? "0.0.0.0",
    port: existing?.port ?? activeProfile?.port ?? 30000,
    ctxSize: settings.ctxSize ?? existing?.ctxSize ?? activeProfile?.ctxSize ?? 262144,
    gpuLayers: settings.gpuLayers ?? existing?.gpuLayers ?? activeProfile?.gpuLayers ?? "all",
    batchSize: settings.batchSize ?? existing?.batchSize ?? activeProfile?.batchSize ?? 2048,
    uBatchSize: settings.uBatchSize ?? existing?.uBatchSize ?? activeProfile?.uBatchSize ?? 512,
    cacheRamMiB: settings.cacheRamMiB ?? existing?.cacheRamMiB ?? activeProfile?.cacheRamMiB ?? 8192,
    cacheTypeK: settings.cacheTypeK ?? existing?.cacheTypeK ?? activeProfile?.cacheTypeK ?? "q4_0",
    cacheTypeV: settings.cacheTypeV ?? existing?.cacheTypeV ?? activeProfile?.cacheTypeV ?? "q4_0",
    cacheReuse: settings.cacheReuse ?? existing?.cacheReuse ?? activeProfile?.cacheReuse ?? 1024,
    specType: settings.specType ?? existing?.specType ?? (supportsMtp ? "draft-mtp" : "none"),
    specDraftNMax: settings.specDraftNMax ?? existing?.specDraftNMax ?? activeProfile?.specDraftNMax ?? 2,
    flashAttention: settings.flashAttention ?? existing?.flashAttention ?? activeProfile?.flashAttention ?? "on",
    backend: existing?.backend === "vulkan" ? "vulkan" : "rocm",
    serverBinary: existing?.serverBinary ?? null,
    runtimeLibraryPath: existing?.runtimeLibraryPath ?? null,
    fanBoostOnBusy: existing?.fanBoostOnBusy ?? false,
    imageMinTokens: settings.imageMinTokens ?? existing?.imageMinTokens ?? activeProfile?.imageMinTokens ?? 1024,
    metrics: settings.metrics ?? existing?.metrics ?? activeProfile?.metrics ?? true,
    jinja: settings.jinja ?? existing?.jinja ?? activeProfile?.jinja ?? true,
    active: existing?.active ?? false,
  };

  await prisma.launchProfile.upsert({
    where: { name },
    create: profile,
    update: profile,
  });
  await prisma.auditLog.create({
    data: {
      action: "model.settings.save",
      subject: modelPath,
      details: JSON.stringify(settings),
    },
  });
  return profile;
}
