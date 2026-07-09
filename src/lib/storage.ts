import { createHash, randomUUID } from "node:crypto";
import { createReadStream, promises as fs } from "node:fs";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { prisma } from "./db";
import { getConfig } from "./config";

export type StorageClass = "production" | "experimental" | "broken" | "unused" | "protected";
export type StorageItem = { path: string; name: string; category: string; sizeBytes: number; classification: StorageClass; protected: boolean; reclaimableBytes: number; lastUsedAt: string | null; checksum: string | null; references: string[] };

const ROOT = "/models";
const TRASH = "/models/.trash";
const execFileAsync = promisify(execFile);

async function sizeOf(filePath: string): Promise<number> {
  const stat = await fs.stat(filePath).catch(() => null);
  if (!stat) return 0;
  if (stat.isFile()) return stat.size;
  const result = await execFileAsync("du", ["-sb", "--", filePath], { timeout: 30_000 }).catch(() => null);
  return result ? Number(result.stdout.trim().split(/\s+/)[0] || 0) : 0;
}

async function checksum(filePath: string): Promise<string> {
  const hash = createHash("sha256");
  await new Promise<void>((resolve, reject) => createReadStream(filePath).on("data", (chunk) => hash.update(chunk)).on("error", reject).on("end", resolve));
  return hash.digest("hex");
}

function withinModels(filePath: string): boolean {
  const resolved = path.resolve(filePath);
  return resolved.startsWith(`${ROOT}/`) && !resolved.startsWith(`${TRASH}/`);
}

export async function getStorageInventory(): Promise<{ root: string; items: StorageItem[]; usedBytes: number; reclaimableBytes: number }> {
  const models = await prisma.modelAsset.findMany({ orderBy: { sizeBytes: "desc" } });
  const items: StorageItem[] = [];
  for (const model of models) {
    const exists = await fs.stat(model.path).catch(() => null);
    if (!exists?.isFile()) continue;
    const references = [model.repo, model.servedAlias].filter(Boolean) as string[];
    const isProtected = model.active || model.defaultModel || model.served;
    const classification: StorageClass = isProtected ? "production" : model.name.toLowerCase().includes("broken") ? "broken" : "experimental";
    items.push({ path: model.path, name: model.name, category: "llm-model", sizeBytes: Number(model.sizeBytes || await sizeOf(model.path)), classification, protected: isProtected, reclaimableBytes: isProtected ? 0 : Number(model.sizeBytes), lastUsedAt: model.updatedAt.toISOString(), checksum: null, references });
  }
  const fixed = [
    ["/opt/ltx2", "video-stack", "protected"], ["/models/wan2-video", "video-models", "production"],
    ["/models/image-gen", "image-models", "production"], ["/models/qwen3-tts", "audio-models", "production"],
    ["/models/appliance-backups", "backups", "protected"],
  ] as const;
  for (const [filePath, category, classification] of fixed) {
    const stat = await fs.stat(filePath).catch(() => null);
    if (!stat) continue;
    items.push({ path: filePath, name: path.basename(filePath), category, sizeBytes: await sizeOf(filePath), classification, protected: true, reclaimableBytes: 0, lastUsedAt: stat.atime.toISOString(), checksum: null, references: ["managed appliance asset"] });
  }
  return { root: getConfig().storageRoot, items, usedBytes: items.reduce((sum, item) => sum + item.sizeBytes, 0), reclaimableBytes: items.reduce((sum, item) => sum + item.reclaimableBytes, 0) };
}

export async function planStorageCleanup(): Promise<{ candidates: StorageItem[]; reclaimableBytes: number }> {
  const inventory = await getStorageInventory();
  const candidates = inventory.items.filter((item) => !item.protected && ["experimental", "broken", "unused"].includes(item.classification));
  return { candidates, reclaimableBytes: candidates.reduce((sum, item) => sum + item.reclaimableBytes, 0) };
}

export async function quarantineStorage(paths: string[]): Promise<{ operationId: string; reclaimedBytes: number }> {
  const plan = await planStorageCleanup();
  const allowed = new Map(plan.candidates.map((item) => [path.resolve(item.path), item]));
  const selected = [...new Set(paths.map((item) => path.resolve(item)))];
  if (!selected.length || selected.some((item) => !withinModels(item) || !allowed.has(item))) throw new Error("Selection contains an unmanaged or protected asset.");
  const operationId = randomUUID();
  const operationDir = path.join(TRASH, operationId);
  await fs.mkdir(operationDir, { recursive: true });
  const records = [];
  let reclaimedBytes = 0;
  for (const source of selected) {
    const item = allowed.get(source)!;
    const digest = await checksum(source);
    const destination = path.join(operationDir, `${records.length}-${path.basename(source)}`);
    await fs.rename(source, destination);
    records.push({ source, destination, checksum: digest, sizeBytes: item.sizeBytes });
    reclaimedBytes += item.sizeBytes;
  }
  await fs.writeFile(path.join(operationDir, "manifest.json"), JSON.stringify({ operationId, createdAt: new Date().toISOString(), purgeAfter: new Date(Date.now() + 7 * 86400_000).toISOString(), records }, null, 2));
  await prisma.auditLog.create({ data: { action: "storage.quarantine", subject: operationId, details: JSON.stringify({ paths: selected, reclaimedBytes }) } });
  return { operationId, reclaimedBytes };
}

export async function restoreStorage(operationId: string): Promise<{ restored: number }> {
  if (!/^[0-9a-f-]{36}$/i.test(operationId)) throw new Error("Invalid operation id.");
  const manifestPath = path.join(TRASH, operationId, "manifest.json");
  const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8")) as { records: Array<{ source: string; destination: string; checksum: string }> };
  for (const record of manifest.records) {
    if (await fs.stat(record.source).catch(() => null)) throw new Error(`Restore target already exists: ${record.source}`);
    if (await checksum(record.destination) !== record.checksum) throw new Error(`Quarantined file checksum failed: ${record.destination}`);
  }
  for (const record of manifest.records) { await fs.mkdir(path.dirname(record.source), { recursive: true }); await fs.rename(record.destination, record.source); }
  await prisma.auditLog.create({ data: { action: "storage.restore", subject: operationId, details: `${manifest.records.length} asset(s) restored` } });
  return { restored: manifest.records.length };
}
