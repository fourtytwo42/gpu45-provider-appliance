import { cancelVideoJob, createVideoJob, deleteVideoJob, extendVideoJob, getVideoSnapshot, startVideoModelDownload } from "@/lib/video";
import type { VideoJob, VideoSnapshot } from "@/lib/video";
import { readFile } from "node:fs/promises";
import path from "node:path";

export const dynamic = "force-dynamic";
const VIDEO_DATA_DIR = process.env.WAN2_API_DATA ?? "/models/wan2-video";

async function readTail(filePath: string, limit = 12000): Promise<string> {
  try {
    const text = await readFile(filePath, "utf8");
    return text.slice(-limit);
  } catch {
    return "";
  }
}

function parseProgress(job: VideoJob, logText: string): Pick<VideoJob, "progress_percent" | "progress_label" | "progress_stage"> {
  if (job.status === "completed") return { progress_percent: 100, progress_label: "Complete", progress_stage: "completed" };
  if (job.status === "failed") return { progress_percent: 100, progress_label: "Failed", progress_stage: "failed" };
  if (job.status === "cancelled") return { progress_percent: 100, progress_label: "Cancelled", progress_stage: "cancelled" };
  if (job.status === "queued") return { progress_percent: 0, progress_label: "Queued", progress_stage: "queued" };
  if (!logText) return { progress_percent: 2, progress_label: "Starting", progress_stage: "starting" };

  const saveMatches = [...logText.matchAll(/Saving video:\s+(\d+)%/g)];
  if (saveMatches.length > 0) {
    const savePercent = Number(saveMatches.at(-1)?.[1] ?? 0);
    return { progress_percent: Math.min(99, 90 + Math.round(savePercent * 0.09)), progress_label: `Saving video ${savePercent}%`, progress_stage: "saving" };
  }
  if (/generated\s+\d+\s+frames/.test(logText)) {
    return { progress_percent: 90, progress_label: "Encoding output", progress_stage: "encoding" };
  }

  const stepMatches = [...logText.matchAll(/(\d+)%\|.*?\|\s*(\d+)\/(\d+)\s*\[/g)];
  if (stepMatches.length > 0) {
    const match = stepMatches.at(-1);
    const step = Number(match?.[2] ?? 0);
    const total = Math.max(1, Number(match?.[3] ?? job.steps ?? 1));
    return { progress_percent: Math.min(89, Math.max(5, Math.round((step / total) * 90))), progress_label: `Denoising step ${step}/${total}`, progress_stage: "denoising" };
  }

  if (logText.includes("pipeline loaded")) return { progress_percent: 5, progress_label: "Preparing denoising", progress_stage: "preparing" };
  if (logText.includes("Loading models from:")) return { progress_percent: 3, progress_label: "Loading model", progress_stage: "loading" };
  return { progress_percent: 2, progress_label: "Starting", progress_stage: "starting" };
}

async function withProgress(snapshot: VideoSnapshot): Promise<VideoSnapshot> {
  const jobs = await Promise.all(snapshot.jobs.map(async (job) => {
    const logText = await readTail(path.join(VIDEO_DATA_DIR, "logs", `${job.id}.log`));
    return { ...job, ...parseProgress(job, logText) };
  }));
  return { ...snapshot, jobs };
}

export async function GET(): Promise<Response> {
  return Response.json(await withProgress(await getVideoSnapshot()));
}

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.json() as Record<string, unknown>;
    const action = String(body.action ?? "");
    if (action === "downloadModel") {
      return Response.json(await startVideoModelDownload(String(body.profile ?? "ltx23-q4")), { status: 202 });
    }
    if (action === "createJob") {
      const job = await createVideoJob(body);
      return Response.json({ ok: true, job }, { status: 202 });
    }
    if (action === "deleteJob") {
      return Response.json(await deleteVideoJob(String(body.id ?? "")));
    }
    if (action === "cancelJob") {
      return Response.json(await cancelVideoJob(String(body.id ?? "")));
    }
    if (action === "extendJob") {
      const job = await extendVideoJob(String(body.id ?? ""), {
        prompt: body.prompt,
        negative_prompt: body.negative_prompt,
        duration_seconds: body.duration_seconds,
        seed: body.seed,
      });
      return Response.json({ ok: true, job }, { status: 202 });
    }
    return Response.json({ error: "Unknown video action." }, { status: 400 });
  } catch (error) {
    return Response.json({ error: error instanceof Error ? error.message : "Video action failed" }, { status: 500 });
  }
}
