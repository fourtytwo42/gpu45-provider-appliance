import { getUnifiedJobs } from "./jobs";
import type { UnifiedJobKind } from "./jobs";

export type OutputKind = "audio" | "audiobook" | "presentation" | "transcript" | "image" | "video" | "benchmark" | "download";

export type OutputRecord = {
  id: string;
  jobId: string;
  kind: OutputKind;
  title: string;
  subtitle?: string | null;
  model?: string | null;
  url?: string | null;
  createdAt?: string | null;
  status: "available" | "record-only";
};

function outputKind(kind: UnifiedJobKind): OutputKind | null {
  if (kind === "tts") return "audio";
  if (kind === "pocket-tts") return "audio";
  if (kind === "audiobook") return "audiobook";
  if (kind === "presentation") return "presentation";
  if (kind === "whisper") return "transcript";
  if (kind === "image") return "image";
  if (kind === "video") return "video";
  if (kind === "benchmark") return "benchmark";
  if (kind === "agentic-benchmark") return "benchmark";
  if (kind === "download") return "download";
  return null;
}

export async function getOutputs(): Promise<{ outputs: OutputRecord[]; kinds: OutputKind[] }> {
  const { jobs } = await getUnifiedJobs();
  const outputs: OutputRecord[] = [];
  for (const job of jobs) {
    if (job.status !== "completed" && !job.outputUrl) continue;
    const kind = outputKind(job.kind);
    if (!kind) continue;
    outputs.push({
      id: `${kind}:${job.sourceId}`,
      jobId: job.id,
      kind,
      title: job.title,
      subtitle: job.subtitle,
      model: job.model,
      url: job.outputUrl,
      createdAt: job.finishedAt ?? job.updatedAt ?? job.createdAt,
      status: job.outputUrl ? "available" : "record-only",
    });
  }
  const kinds = Array.from(new Set(outputs.map((output) => output.kind))).sort() as OutputKind[];
  return { outputs, kinds };
}
