import { createHash, randomBytes } from "node:crypto";
import { z } from "zod";
import { prisma } from "./db";
import type { ApiKeyRecord } from "./types";

const createSchema = z.object({
  name: z.string().trim().max(100).optional(),
  expiresAt: z.string().datetime().optional().nullable(),
});

export function hashApiKey(key: string): string {
  return createHash("sha256").update(key).digest("hex");
}

export async function listApiKeys(): Promise<ApiKeyRecord[]> {
  const keys = await prisma.apiKey.findMany({ orderBy: { createdAt: "desc" } });
  const usage = await prisma.apiKeyUsage.groupBy({
    by: ["apiKeyId", "model"],
    where: { apiKeyId: { not: null } },
    _count: { _all: true },
    _sum: { promptTokens: true, completionTokens: true },
  });
  return keys.map((key) => ({
    id: key.id,
    name: key.name,
    keyPrefix: key.keyPrefix,
    expiresAt: key.expiresAt?.toISOString() ?? null,
    suspendedAt: key.suspendedAt?.toISOString() ?? null,
    lastUsedAt: key.lastUsedAt?.toISOString() ?? null,
    requestCount: key.requestCount,
    promptTokens: key.promptTokens,
    completionTokens: key.completionTokens,
    createdAt: key.createdAt.toISOString(),
    models: usage.filter((row) => row.apiKeyId === key.id).map((row) => ({
      model: row.model,
      requests: row._count._all,
      promptTokens: row._sum.promptTokens ?? 0,
      completionTokens: row._sum.completionTokens ?? 0,
    })),
  }));
}

export async function createApiKey(input: unknown): Promise<{ key: string; record: ApiKeyRecord }> {
  const parsed = createSchema.parse(input);
  const key = `gpu45_${randomBytes(24).toString("base64url")}`;
  const created = await prisma.apiKey.create({
    data: {
      name: parsed.name || null,
      keyHash: hashApiKey(key),
      keyPrefix: `${key.slice(0, 13)}...`,
      expiresAt: parsed.expiresAt ? new Date(parsed.expiresAt) : null,
    },
  });
  await prisma.auditLog.create({ data: { action: "api_key.create", subject: created.id, details: created.name ?? created.keyPrefix } });
  return { key, record: (await listApiKeys()).find((item) => item.id === created.id)! };
}

export async function setApiKeySuspended(id: string, suspended: boolean): Promise<void> {
  const key = await prisma.apiKey.update({ where: { id }, data: { suspendedAt: suspended ? new Date() : null } });
  await prisma.auditLog.create({ data: { action: suspended ? "api_key.suspend" : "api_key.resume", subject: id, details: key.name ?? key.keyPrefix } });
}

export async function deleteApiKey(id: string): Promise<void> {
  const key = await prisma.apiKey.delete({ where: { id } });
  await prisma.auditLog.create({ data: { action: "api_key.delete", subject: id, details: key.name ?? key.keyPrefix } });
}

export async function getEndpointSettings(): Promise<{ allowAnonymous: boolean }> {
  const setting = await prisma.endpointSetting.upsert({ where: { id: "default" }, create: { id: "default", allowAnonymous: true }, update: {} });
  return { allowAnonymous: setting.allowAnonymous };
}

export async function setAllowAnonymous(allowAnonymous: boolean): Promise<void> {
  await prisma.endpointSetting.upsert({ where: { id: "default" }, create: { id: "default", allowAnonymous }, update: { allowAnonymous } });
  await prisma.auditLog.create({ data: { action: "endpoint.auth", subject: "allowAnonymous", details: String(allowAnonymous) } });
}
