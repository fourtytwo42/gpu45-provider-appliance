import { createHash, randomUUID } from "node:crypto";
import { createReadStream, promises as fs } from "node:fs";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { prisma } from "./db";
import { getConfig } from "./config";

export type StorageClass = "production" | "experimental" | "broken" | "unused" | "protected";
export type StorageVerification = "verified" | "referenced" | "unverified";
export type StorageItem = { path: string; name: string; category: string; sizeBytes: number; classification: StorageClass; protected: boolean; reclaimableBytes: number; lastUsedAt: string | null; checksum: string | null; references: string[]; verificationStatus: StorageVerification; quarantineExpiresAt?: string | null; restoreAction?: string | null };

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
  const stat = await fs.stat(filePath);
  if (stat.isDirectory()) {
    return createHash("sha256").update(`${stat.size}:${stat.mtimeMs}:${await sizeOf(filePath)}`).digest("hex");
  }
  const hash = createHash("sha256");
  await new Promise<void>((resolve, reject) => createReadStream(filePath).on("data", (chunk) => hash.update(chunk)).on("error", reject).on("end", resolve));
  return hash.digest("hex");
}

export function withinManagedStorage(filePath: string): boolean {
  const resolved = path.posix.resolve(filePath.replaceAll("\\", "/"));
  return (resolved.startsWith(`${ROOT}/`) && !resolved.startsWith(`${TRASH}/`)) || resolved === "/opt/ltx2";
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
    items.push({ path: model.path, name: model.name, category: "llm-model", sizeBytes: Number(model.sizeBytes || await sizeOf(model.path)), classification, protected: isProtected, reclaimableBytes: isProtected ? 0 : Number(model.sizeBytes), lastUsedAt: model.updatedAt.toISOString(), checksum: null, references, verificationStatus: isProtected ? "referenced" : "unverified" });
  }
  const fixed = [
    ["/models/wan2-video", "video-models", "production", true, "wan2-video-api.service"],
    ["/models/image-gen", "image-models", "production", true, "gpu45-image-api.service"],
    ["/models/qwen3-tts", "audio-models", "production", true, "qwen3-tts-api.service"],
    ["/models/whisper", "speech-models", "production", true, "gpu45-whisper-api.service"],
    ["/models/appliance-backups", "backups", "protected", true, "restic local repository"],
    ["/opt/gpu45/releases", "releases", "protected", true, "blue-green deployment"],
    ["/opt/ltx2", "video-stack", "unused", false, "No active service, profile, job, or runtime import"],
    ["/var/crash", "crash-files", "broken", false, "Crash retention policy"],
  ] as const;
  for (const [filePath, category, classification, isProtected, reference] of fixed) {
    const stat = await fs.stat(filePath).catch(() => null);
    if (!stat) continue;
    let sizeBytes = await sizeOf(filePath);
    if (filePath === "/var/crash" && sizeBytes === 0) {
      sizeBytes = await fs.readFile("/var/lib/gpu45/storage-retention.json", "utf8")
        .then((value) => Number((JSON.parse(value) as { crashBytes?: number }).crashBytes ?? 0)).catch(() => 0);
    }
    items.push({ path: filePath, name: path.basename(filePath), category, sizeBytes, classification, protected: isProtected, reclaimableBytes: isProtected ? 0 : sizeBytes, lastUsedAt: stat.mtime.toISOString(), checksum: null, references: [reference], verificationStatus: isProtected ? "referenced" : "verified" });
  }
  const quarantined = await fs.readdir(TRASH, { withFileTypes: true }).catch(() => []);
  for (const entry of quarantined.filter((item) => item.isDirectory())) {
    const operationPath = path.join(TRASH, entry.name);
    const manifest = await fs.readFile(path.join(operationPath, "manifest.json"), "utf8").then((value) => JSON.parse(value) as { purgeAfter?: string }).catch(() => null);
    const stat = await fs.stat(operationPath);
    const sizeBytes = await sizeOf(operationPath);
    items.push({ path: operationPath, name: entry.name, category: "quarantine", sizeBytes, classification: "unused", protected: false, reclaimableBytes: sizeBytes, lastUsedAt: stat.mtime.toISOString(), checksum: null, references: [manifest ? "recoverable quarantine" : "legacy unreferenced trash"], verificationStatus: manifest ? "verified" : "unverified", quarantineExpiresAt: manifest?.purgeAfter ?? null, restoreAction: manifest ? entry.name : null });
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
  if (!selected.length || selected.some((item) => !withinManagedStorage(item) || !allowed.has(item))) throw new Error("Selection contains an unmanaged or protected asset.");
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
