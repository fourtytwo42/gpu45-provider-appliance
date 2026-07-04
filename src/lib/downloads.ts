import { promises as fs } from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { z } from "zod";
import { prisma } from "./db";
import { getConfig, isLiveRuntime } from "./config";
import type { DownloadJob } from "./types";
import { classifyModelAsset } from "./model-assets";
import { modelAlias } from "./model-catalog";

const requestSchema = z.object({
  repoId: z.string().regex(/^[\w.-]+\/[\w.-]+$/).max(200),
  fileName: z.string().min(1).max(500).refine((value) => !value.includes("..") && !path.isAbsolute(value)),
  revision: z.string().regex(/^[\w./-]+$/).max(120).default("main"),
});

function serialize(job: Awaited<ReturnType<typeof prisma.downloadJob.create>>): DownloadJob {
  return {
    ...job,
    status: job.status as DownloadJob["status"],
    bytesDownloaded: Number(job.bytesDownloaded),
    totalBytes: Number(job.totalBytes),
    createdAt: job.createdAt.toISOString(),
    updatedAt: job.updatedAt.toISOString(),
  };
}

export async function listDownloadJobs(): Promise<DownloadJob[]> {
  const jobs = await prisma.downloadJob.findMany({ orderBy: { createdAt: "desc" }, take: 20 });
  return jobs.map(serialize);
}

export async function recoverInterruptedDownloads(): Promise<number> {
  const result = await prisma.downloadJob.updateMany({
    where: { status: "downloading" },
    data: { status: "queued", bytesDownloaded: BigInt(0), error: "Worker restarted; download requeued." },
  });
  return result.count;
}

export async function deleteDownloadJob(id: string): Promise<boolean> {
  const job = await prisma.downloadJob.findUnique({ where: { id } });
  if (!job || job.status === "downloading") return false;
  await prisma.downloadJob.delete({ where: { id } });
  return true;
}

export async function clearFinishedDownloadJobs(): Promise<number> {
  const result = await prisma.downloadJob.deleteMany({ where: { status: { in: ["completed", "failed", "cancelled"] } } });
  return result.count;
}

async function queueSingleDownload(input: z.infer<typeof requestSchema>): Promise<DownloadJob> {
  const parsed = requestSchema.parse(input);
  const cfg = getConfig();
  const targetPath = path.join(cfg.downloadStaging, parsed.repoId.replaceAll("/", "--"), parsed.revision, parsed.fileName);
  const existing = await prisma.downloadJob.findFirst({
    where: { targetPath, status: { in: ["queued", "downloading", "completed"] } },
    orderBy: { createdAt: "desc" },
  });
  if (existing && (existing.status !== "completed" || await fs.stat(targetPath).then(() => true).catch(() => false))) {
    return serialize(existing);
  }
  const job = await prisma.downloadJob.create({ data: { ...parsed, targetPath } });
  await prisma.auditLog.create({
    data: { action: "model.download.queued", subject: `${parsed.repoId}/${parsed.fileName}`, details: targetPath },
  });
  return serialize(job);
}

async function discoverMtpCompanions(repoId: string, revision: string, primaryFile: string): Promise<string[]> {
  if (classifyModelAsset(primaryFile) !== "model") return [];
  const cfg = getConfig();
  const response = await fetch(`https://huggingface.co/api/models/${repoId}/revision/${encodeURIComponent(revision)}`, {
    headers: cfg.hfToken ? { Authorization: `Bearer ${cfg.hfToken}` } : undefined,
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Unable to inspect MTP companions: Hugging Face returned ${response.status}`);
  const metadata = await response.json() as { siblings?: Array<{ rfilename?: string }> };
  return (metadata.siblings ?? [])
    .map((file) => file.rfilename ?? "")
    .filter((file) => file !== primaryFile && file.toLowerCase().endsWith(".gguf") && classifyModelAsset(file) === "mtp");
}

export async function queueDownloadBundle(input: unknown): Promise<{ primary: DownloadJob; companions: DownloadJob[] }> {
  const parsed = requestSchema.parse(input);
  const primary = await queueSingleDownload(parsed);
  const companionFiles = await discoverMtpCompanions(parsed.repoId, parsed.revision, parsed.fileName);
  const companions = await Promise.all(companionFiles.map((fileName) => queueSingleDownload({ ...parsed, fileName })));
  return { primary, companions };
}

export async function queueDownload(input: unknown): Promise<DownloadJob> {
  return (await queueDownloadBundle(input)).primary;
}

async function downloadWithCurl(
  url: string,
  partialPath: string,
  token: string | undefined,
  onProgress: (bytes: number) => Promise<void>,
): Promise<void> {
  const configPath = `${partialPath}.curl-config`;
  const args = ["--location", "--fail", "--silent", "--show-error", "--output", partialPath];
  if (token) {
    const escaped = token.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
    await fs.writeFile(configPath, `header = "Authorization: Bearer ${escaped}"\n`, { mode: 0o600 });
    args.push("--config", configPath);
  }
  args.push(url);

  let finished = false;
  let stderr = "";
  const completion = new Promise<number>((resolve, reject) => {
    const child = spawn("curl", args, { stdio: ["ignore", "ignore", "pipe"] });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr = `${stderr}${chunk.toString()}`.slice(-8000);
    });
    child.on("error", (error) => {
      finished = true;
      reject(error);
    });
    child.on("close", (code) => {
      finished = true;
      resolve(code ?? 1);
    });
  });

  try {
    while (!finished) {
      await new Promise((resolve) => setTimeout(resolve, 750));
      const stat = await fs.stat(partialPath).catch(() => null);
      if (stat) await onProgress(stat.size);
    }
    const code = await completion;
    if (code !== 0) throw new Error(`curl exited ${code}: ${stderr.trim() || "download failed"}`);
  } finally {
    await fs.rm(configPath, { force: true }).catch(() => undefined);
  }
}

export async function processNextDownload(): Promise<boolean> {
  if (!isLiveRuntime()) return false;
  const queued = await prisma.downloadJob.findFirst({ where: { status: "queued" }, orderBy: { createdAt: "asc" } });
  if (!queued) return false;
  const claimed = await prisma.downloadJob.updateMany({
    where: { id: queued.id, status: "queued" },
    data: { status: "downloading", error: null },
  });
  if (claimed.count !== 1) return false;

  const cfg = getConfig();
  const partialPath = `${queued.targetPath}.part`;
  try {
    await fs.mkdir(path.dirname(queued.targetPath), { recursive: true });
    const url = `https://huggingface.co/${queued.repoId}/resolve/${queued.revision}/${queued.fileName.split("/").map(encodeURIComponent).join("/")}`;
    const headers = cfg.hfToken ? { Authorization: `Bearer ${cfg.hfToken}` } : undefined;
    const response = await fetch(url, { method: "HEAD", headers, redirect: "follow" });
    if (!response.ok) throw new Error(`Hugging Face returned ${response.status}`);
    const totalBytes = Number(response.headers.get("content-length") ?? 0);
    await prisma.downloadJob.update({ where: { id: queued.id }, data: { totalBytes: BigInt(totalBytes) } });

    console.log(`[download] started ${queued.repoId}/${queued.fileName} (${totalBytes || "unknown"} bytes)`);
    let downloaded = 0;
    await downloadWithCurl(url, partialPath, cfg.hfToken, async (bytes) => {
      downloaded = bytes;
      await prisma.downloadJob.update({ where: { id: queued.id }, data: { bytesDownloaded: BigInt(bytes) } });
    });
    const partialStat = await fs.stat(partialPath);
    downloaded = partialStat.size;
    await prisma.downloadJob.update({ where: { id: queued.id }, data: { bytesDownloaded: BigInt(downloaded) } });
    await fs.rename(partialPath, queued.targetPath);
    const sizeBytes = (await fs.stat(queued.targetPath)).size;
    await prisma.$transaction([
      prisma.downloadJob.update({
        where: { id: queued.id },
        data: { status: "completed", bytesDownloaded: BigInt(sizeBytes), totalBytes: BigInt(sizeBytes) },
      }),
      prisma.modelAsset.upsert({
        where: { path: queued.targetPath },
        create: {
          name: queued.fileName,
          path: queued.targetPath,
          repo: queued.repoId,
          revision: queued.revision,
          sizeBytes: BigInt(sizeBytes),
          multimodal: /mmproj|\bvl\b/i.test(queued.fileName),
          active: false,
          served: classifyModelAsset(queued.fileName) === "model",
          servedAlias: classifyModelAsset(queued.fileName) === "model" ? modelAlias(queued.fileName, queued.targetPath) : null,
        },
        update: { sizeBytes: BigInt(sizeBytes), repo: queued.repoId, revision: queued.revision },
      }),
      prisma.auditLog.create({
        data: { action: "model.download.completed", subject: `${queued.repoId}/${queued.fileName}`, details: queued.targetPath },
      }),
    ]);
    console.log(`[download] completed ${queued.fileName} (${sizeBytes} bytes)`);
  } catch (error) {
    await fs.rm(partialPath, { force: true }).catch(() => undefined);
    const message = error instanceof Error ? error.message : "Download failed";
    await prisma.downloadJob.update({ where: { id: queued.id }, data: { status: "failed", error: message.slice(0, 500) } });
    await prisma.auditLog.create({ data: { action: "model.download.failed", subject: queued.fileName, details: message.slice(0, 500) } });
    console.error(`[download] failed ${queued.fileName}: ${message}`);
  }
  return true;
}
