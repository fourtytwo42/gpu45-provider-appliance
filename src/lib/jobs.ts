import { prisma } from "./db";
import { deleteDownloadJob } from "./downloads";
import { deleteImageJob } from "./images";
import { deleteTtsAudiobook, deleteTtsModel, deleteTtsPresentation, deleteTtsSynthesisJob, deleteTtsVoiceJob, getTtsAudiobook, getTtsPresentation, stopTtsAudiobook, stopTtsPresentation } from "./tts";
import { cancelVideoJob, deleteVideoJob } from "./video";
import { deleteWhisperJob } from "./whisper";
import { deletePocketTtsJob } from "./pocket-tts";
import { readStoredJobHistory } from "./job-history";
import { agenticCampaignAction, listAgenticCampaigns } from "./agentic-benchmarks";
import { deleteMusicJob, getMusicSnapshot, musicJobAction } from "./music";

export type UnifiedJobStatus = "queued" | "waiting" | "running" | "paused" | "restoring" | "unknown" | "completed" | "failed" | "cancelled" | "stopped" | "needs_review";
export type UnifiedJobKind = "download" | "benchmark" | "agentic-benchmark" | "tts" | "pocket-tts" | "audiobook" | "whisper" | "image" | "video" | "music" | "model-training" | "voice" | "presentation";
export type UnifiedJobAction = "cancel" | "delete" | "retry" | "download";

export type UnifiedJob = {
  id: string;
  sourceId: string;
  kind: UnifiedJobKind;
  title: string;
  subtitle?: string | null;
  status: UnifiedJobStatus;
  displayStatus?: string | null;
  stage?: string | null;
  progressPercent?: number | null;
  progressLabel?: string | null;
  etaSeconds?: number | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  outputUrl?: string | null;
  error?: string | null;
  technicalError?: string | null;
  userMessage?: string | null;
  model?: string | null;
  actions?: UnifiedJobAction[];
  availableActions?: UnifiedJobAction[];
  outputPreview?: string | null;
  actionLabels?: Partial<Record<UnifiedJobAction, string>>;
  resourceImpact?: string | null;
  resourceOwner?: string | null;
  waitReason?: string | null;
  preemptible?: boolean | null;
  resumePolicy?: string | null;
  recoveryState?: string | null;
};

export type JobsSummary = { total: number; active: number; queued: number; failed: number; completed: number };

export function normalizeStatus(status: string): UnifiedJobStatus {
  if (status === "complete" || status === "ready") return "completed";
  if (status === "training") return "running";
  if (status === "preparing") return "waiting";
  if (["queued", "waiting", "running", "paused", "restoring", "completed", "failed", "cancelled", "stopped", "needs_review"].includes(status)) return status as UnifiedJobStatus;
  return "unknown";
}

function isActive(status: UnifiedJobStatus): boolean { return ["queued", "waiting", "running", "paused", "restoring"].includes(status); }
function sortDate(job: UnifiedJob): string { return job.updatedAt ?? job.finishedAt ?? job.startedAt ?? job.createdAt ?? ""; }

function actionsFor(kind: UnifiedJobKind, status: UnifiedJobStatus, hasOutput = false): UnifiedJobAction[] {
  const actions: UnifiedJobAction[] = [];
  if (hasOutput) actions.push("download");
  if (kind === "audiobook" && (status === "running" || status === "queued")) actions.push("cancel");
  if (kind === "presentation" && (status === "running" || status === "queued")) actions.push("cancel");
  if (kind === "video" && (status === "running" || status === "queued")) actions.push("cancel");
  if (kind === "music" && ["queued", "waiting", "running", "restoring"].includes(status)) actions.push("cancel");
  if (kind === "music" && ["failed", "cancelled"].includes(status)) actions.push("retry");
  if (kind === "agentic-benchmark" && ["queued", "waiting", "running", "paused", "restoring"].includes(status)) actions.push("cancel");
  if (["download", "tts", "pocket-tts", "audiobook", "presentation", "whisper", "image", "video", "music", "model-training", "voice"].includes(kind) && !["running", "waiting", "restoring", "unknown"].includes(status)) actions.push("delete");
  return actions;
}

function withActions(job: UnifiedJob): UnifiedJob {
  const actions = actionsFor(job.kind, job.status, Boolean(job.outputUrl));
  const actionLabels: UnifiedJob["actionLabels"] = { cancel: "Cancel", delete: "Delete", download: "Open output", retry: "Retry" };
  const displayStatus = job.status === "needs_review" ? "Needs review" : job.status.charAt(0).toUpperCase() + job.status.slice(1);
  const userMessage = job.error ? job.error.split("\n").find((line) => line.trim().length > 0)?.slice(0, 220) ?? "This job failed. Open technical details for more information." : null;
  return { ...job, displayStatus, technicalError: job.error, userMessage, actions, availableActions: actions, actionLabels, outputPreview: job.outputUrl };
}


export async function getUnifiedJobs(): Promise<{ jobs: UnifiedJob[]; summary: JobsSummary }> {
  const jobs: UnifiedJob[] = [];
  const [downloads, benchmarks, agenticCampaigns, music] = await Promise.all([
    prisma.downloadJob.findMany({ orderBy: { updatedAt: "desc" }, take: 50 }).catch(() => []),
    prisma.benchmarkRun.findMany({ orderBy: { createdAt: "desc" }, take: 30 }).catch(() => []),
    listAgenticCampaigns().catch(() => []),
    getMusicSnapshot(),
  ]);
  const stored = readStoredJobHistory();
  const tts = stored.tts;
  const pocketTts = { jobs: stored.pocketTts };
  const images = { jobs: stored.images };
  const videos = { jobs: stored.videos };
  const whisper = { jobs: stored.whisper };

  for (const job of downloads) {
    jobs.push({ id: `download:${job.id}`, sourceId: job.id, kind: "download", title: job.fileName, subtitle: job.repoId, status: normalizeStatus(job.status), progressPercent: Number(job.totalBytes) > 0 ? Math.round((Number(job.bytesDownloaded) / Number(job.totalBytes)) * 1000) / 10 : null, progressLabel: `${Number(job.bytesDownloaded).toLocaleString()} / ${Number(job.totalBytes).toLocaleString()} bytes`, createdAt: job.createdAt.toISOString(), updatedAt: job.updatedAt.toISOString(), error: job.error });
  }
  for (const run of benchmarks) {
    jobs.push({ id: `benchmark:${run.id}`, sourceId: run.id, kind: "benchmark", title: `Benchmark: ${run.modelName}`, subtitle: `${run.promptTokensPerSecond.toFixed(1)} prompt tok/s, ${run.generationTokensPerSecond.toFixed(1)} decode tok/s`, status: "completed", progressPercent: 100, createdAt: run.createdAt.toISOString(), finishedAt: run.createdAt.toISOString(), model: run.modelName });
  }
  for (const campaign of agenticCampaigns) {
    const status = normalizeStatus(campaign.status);
    const summary = Object.entries(campaign.runSummary ?? {}).map(([key, value]) => `${value} ${key}`).join(", ");
    jobs.push({
      id: `agentic-benchmark:${campaign.id}`, sourceId: campaign.id, kind: "agentic-benchmark",
      title: campaign.name, subtitle: summary || `${campaign.preset} campaign`, status,
      progressLabel: summary || null, createdAt: campaign.created_at, updatedAt: campaign.updated_at,
      outputUrl: status === "completed" ? `/api/agentic-benchmarks/${encodeURIComponent(campaign.id)}/export?format=markdown` : null,
      resourceImpact: "Low-priority appliance benchmark; interactive Codex requests preempt it at a task boundary.",
      preemptible: true, resumePolicy: "Interrupted tasks restart in a clean sandbox.",
    });
  }
  if (tts) {
    for (const job of tts.voiceJobs) jobs.push({ id: `voice:${job.id}`, sourceId: job.id, kind: "voice", title: job.name ? `Voice: ${job.name}` : "Voice generation", subtitle: job.kind === "voice_import" ? "Imported reference voice" : "Prompt-designed reference voice", status: normalizeStatus(job.status), progressPercent: job.progress_percent, progressLabel: job.progress_label, etaSeconds: job.eta_seconds, createdAt: job.created_at, updatedAt: job.updated_at, startedAt: job.started_at, finishedAt: job.finished_at, error: job.error });
    for (const model of tts.models) jobs.push({ id: `model-training:${model.id}`, sourceId: model.id, kind: "model-training", title: `Voice model: ${model.name}`, subtitle: model.speaker_name ?? model.model_path, status: normalizeStatus(model.status), progressPercent: model.status === "ready" ? 100 : model.progress_percent, progressLabel: model.progress_label, etaSeconds: model.eta_seconds, createdAt: model.created_at, updatedAt: model.updated_at, startedAt: model.started_at, finishedAt: model.finished_at, error: model.error });
    for (const job of tts.synthesisJobs) { const status = normalizeStatus(job.status); jobs.push({ id: `tts:${job.id}`, sourceId: job.id, kind: "tts", title: job.model_name ? `Speech: ${job.model_name}` : "Speech synthesis", subtitle: `${job.text_chars.toLocaleString()} characters`, status, progressPercent: job.progress_percent, progressLabel: job.progress_label, etaSeconds: job.eta_seconds, createdAt: job.created_at, updatedAt: job.updated_at, startedAt: job.started_at, finishedAt: job.finished_at, outputUrl: status === "completed" ? `/api/tts/synthesis/audio?id=${encodeURIComponent(job.id)}&download=1` : null, error: job.error, model: job.model_name }); }
    for (const job of tts.audiobookJobs) { const status = normalizeStatus(job.status); jobs.push({ id: `audiobook:${job.id}`, sourceId: job.id, kind: "audiobook", title: job.title, subtitle: `${job.completed_chunks}/${job.total_chunks} chunks - ${job.source_filename}`, status, progressPercent: job.progress_percent, progressLabel: job.progress_label, etaSeconds: job.eta_seconds, createdAt: job.created_at, updatedAt: job.updated_at, startedAt: job.started_at, finishedAt: job.finished_at, outputUrl: `/api/tts/audiobook/audio?id=${encodeURIComponent(job.id)}&download=1`, error: job.error, model: job.model_name }); }
    for (const job of tts.presentationJobs) { const status = normalizeStatus(job.status); jobs.push({ id: `presentation:${job.id}`, sourceId: job.id, kind: "presentation", title: job.title, subtitle: `${job.completed_slides}/${job.total_slides} slides - ${job.source_filename}`, status, progressPercent: job.progress_percent, progressLabel: job.progress_label, etaSeconds: job.eta_seconds, createdAt: job.created_at, updatedAt: job.updated_at, startedAt: job.started_at, finishedAt: job.finished_at, outputUrl: job.output_path || status === "completed" ? `/api/tts/presentation/output?id=${encodeURIComponent(job.id)}&download=1` : null, error: job.error, model: job.model_name }); }
  }
  if (pocketTts) {
    for (const job of pocketTts.jobs) {
      const status = normalizeStatus(job.status);
      jobs.push({
        id: `pocket-tts:${job.id}`, sourceId: job.id, kind: "pocket-tts",
        title: `Pocket speech: ${job.voice_name}`, subtitle: `${job.language} - ${job.text_chars.toLocaleString()} characters`,
        status, progressPercent: job.progress_percent, progressLabel: job.progress_label,
        createdAt: job.created_at, updatedAt: job.updated_at, finishedAt: job.finished_at,
        outputUrl: status === "completed" ? `/api/tts/pocket/audio?id=${encodeURIComponent(job.id)}&download=1` : null,
        error: job.error, model: "Pocket TTS", resourceImpact: "CPU only; the active LLM remains loaded.",
      });
    }
  }
  if (images) for (const job of images.jobs) { const status = normalizeStatus(job.status); jobs.push({ id: `image:${job.id}`, sourceId: job.id, kind: "image", title: job.profile_name ?? job.profile, subtitle: job.prompt, status, progressPercent: job.progress_percent ?? (status === "completed" ? 100 : null), progressLabel: job.progress_label ?? (job.progress_step && job.progress_total ? `${job.progress_step}/${job.progress_total} steps` : null), etaSeconds: job.eta_seconds, createdAt: job.created_at, updatedAt: job.updated_at ?? job.completed_at ?? job.started_at ?? job.created_at, startedAt: job.started_at, finishedAt: job.completed_at, outputUrl: status === "completed" ? `/api/images/output?id=${encodeURIComponent(job.id)}` : null, error: job.error, model: job.profile_name ?? job.profile }); }
  if (videos) for (const job of videos.jobs) { const status = normalizeStatus(job.status); jobs.push({ id: `video:${job.id}`, sourceId: job.id, kind: "video", title: job.profile_name ?? job.profile ?? "Video generation", subtitle: job.prompt, status, progressPercent: job.progress_percent ?? (status === "completed" ? 100 : null), progressLabel: job.progress_label ?? job.progress_stage, createdAt: job.created_at, updatedAt: job.completed_at ?? job.started_at ?? job.created_at, startedAt: job.started_at, finishedAt: job.completed_at, outputUrl: status === "completed" ? `/api/video/output?id=${encodeURIComponent(job.id)}` : null, error: job.error, model: job.profile_name ?? job.profile }); }
  for (const job of music.jobs) {
    const status = normalizeStatus(job.status);
    const caption = String(job.payload.caption ?? "").trim();
    jobs.push({
      id: `music:${job.id}`, sourceId: job.id, kind: "music", title: job.profile_name ?? job.profile_id,
      subtitle: caption || `${job.mode} - ${job.task_type}`, status, stage: job.stage,
      progressPercent: job.progress, progressLabel: job.stage.replaceAll("-", " "), etaSeconds: job.eta_seconds,
      createdAt: job.created_at, updatedAt: job.updated_at, startedAt: job.started_at, finishedAt: job.completed_at,
      outputUrl: status === "completed" ? `/api/music/jobs/${encodeURIComponent(job.id)}/output?asset=master` : null,
      error: job.error, model: job.profile_name ?? job.profile_id,
      resourceImpact: "Exclusive GPU music generation; the prior LLM is restored after release.",
      preemptible: job.profile_id.startsWith("levo") ? true : false,
      resumePolicy: job.profile_id.startsWith("levo") ? "Resumes from the last completed phase." : "Restarts atomically after interruption.",
    });
  }
  if (whisper) for (const job of whisper.jobs) { const status = normalizeStatus(job.status); jobs.push({ id: `whisper:${job.id}`, sourceId: job.id, kind: "whisper", title: `Transcript: ${job.filename}`, subtitle: `${job.model} - ${job.task}`, status, progressPercent: job.progress_percent ?? (status === "completed" ? 100 : null), progressLabel: job.progress_label, etaSeconds: job.eta_seconds, createdAt: job.created_at, updatedAt: job.completed_at ?? job.started_at ?? job.created_at, startedAt: job.started_at, finishedAt: job.completed_at, outputUrl: status === "completed" ? `/api/whisper/output?id=${encodeURIComponent(job.id)}&download=1` : null, error: job.error, model: job.model }); }

  const normalizedJobs = jobs.map(withActions);
  normalizedJobs.sort((a, b) => sortDate(b).localeCompare(sortDate(a)));
  const summary = normalizedJobs.reduce<JobsSummary>((acc, job) => { acc.total += 1; if (job.status === "queued") acc.queued += 1; if (job.status === "failed") acc.failed += 1; if (job.status === "completed") acc.completed += 1; if (isActive(job.status)) acc.active += 1; return acc; }, { total: 0, active: 0, queued: 0, failed: 0, completed: 0 });
  return { jobs: normalizedJobs, summary };
}

export async function getUnifiedJob(id: string): Promise<UnifiedJob | null> {
  const { jobs } = await getUnifiedJobs();
  return jobs.find((job) => job.id === id) ?? null;
}

export function paginateItems<T>(items: T[], cursor = 0, limit = 50): {
  items: T[];
  nextCursor: number | null;
  total: number;
} {
  const offset = Math.max(0, Math.floor(Number.isFinite(cursor) ? cursor : 0));
  const pageSize = Math.max(1, Math.min(100, Math.floor(Number.isFinite(limit) ? limit : 50)));
  const page = items.slice(offset, offset + pageSize);
  return { items: page, nextCursor: offset + page.length < items.length ? offset + page.length : null, total: items.length };
}

export async function getUnifiedJobItems(id: string, cursor = 0, limit = 50): Promise<{
  items: unknown[];
  nextCursor: number | null;
  total: number;
}> {
  const [kind, sourceId] = id.split(":", 2);
  let items: unknown[] = [];
  if (kind === "audiobook" && sourceId) items = (await getTtsAudiobook(sourceId)).chunks;
  if (kind === "presentation" && sourceId) items = (await getTtsPresentation(sourceId)).slides;
  return paginateItems(items, cursor, limit);
}

export async function performUnifiedJobAction(id: string, action: UnifiedJobAction): Promise<{ ok: boolean; message: string }> {
  const [kind, sourceId] = id.split(":", 2) as [UnifiedJobKind | undefined, string | undefined];
  if (!kind || !sourceId) return { ok: false, message: "Invalid job id." };
  if (action === "download") return { ok: true, message: "Open the output link directly." };

  if (kind === "download" && action === "delete") {
    const ok = await deleteDownloadJob(sourceId);
    return { ok, message: ok ? "Download queue record deleted." : "Active or unknown download cannot be deleted." };
  }
  if (kind === "tts" && action === "delete") { await deleteTtsSynthesisJob(sourceId); return { ok: true, message: "Speech job deleted." }; }
  if (kind === "pocket-tts" && action === "delete") { await deletePocketTtsJob(sourceId); return { ok: true, message: "Pocket TTS job deleted." }; }
  if (kind === "audiobook" && action === "cancel") { await stopTtsAudiobook(sourceId); return { ok: true, message: "Audiobook stop requested." }; }
  if (kind === "audiobook" && action === "delete") { await deleteTtsAudiobook(sourceId); return { ok: true, message: "Audiobook deleted." }; }
  if (kind === "presentation" && action === "cancel") { await stopTtsPresentation(sourceId); return { ok: true, message: "Presentation stop requested." }; }
  if (kind === "presentation" && action === "delete") { await deleteTtsPresentation(sourceId); return { ok: true, message: "Presentation job deleted." }; }
  if (kind === "voice" && action === "delete") { await deleteTtsVoiceJob(sourceId); return { ok: true, message: "Voice job deleted." }; }
  if (kind === "model-training" && action === "delete") { await deleteTtsModel(sourceId); return { ok: true, message: "Voice model deleted." }; }
  if (kind === "whisper" && action === "delete") { await deleteWhisperJob(sourceId); return { ok: true, message: "Transcript job deleted." }; }
  if (kind === "image" && action === "delete") { await deleteImageJob(sourceId); return { ok: true, message: "Image job deleted." }; }
  if (kind === "video" && action === "cancel") { await cancelVideoJob(sourceId); return { ok: true, message: "Video cancellation requested." }; }
  if (kind === "video" && action === "delete") { await deleteVideoJob(sourceId); return { ok: true, message: "Video job deleted." }; }
  if (kind === "music" && action === "cancel") { await musicJobAction(sourceId, "cancel"); return { ok: true, message: "Music cancellation requested." }; }
  if (kind === "music" && action === "retry") { await musicJobAction(sourceId, "retry"); return { ok: true, message: "Music job queued for retry." }; }
  if (kind === "music" && action === "delete") { await deleteMusicJob(sourceId); return { ok: true, message: "Music job and associated files deleted." }; }
  if (kind === "agentic-benchmark" && action === "cancel") {
    const result = await agenticCampaignAction(sourceId, "cancel");
    return { ok: result.ok, message: result.ok ? "Benchmark cancellation requested." : "Benchmark campaign was not found." };
  }

  return { ok: false, message: `${action} is not supported for ${kind} jobs.` };
}
