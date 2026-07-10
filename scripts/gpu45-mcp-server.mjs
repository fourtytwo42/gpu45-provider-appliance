#!/usr/bin/env node
import { createInterface } from "node:readline";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { homedir } from "node:os";
import { fileURLToPath } from "node:url";

export const DEFAULT_BASE_URL = process.env.GPU45_APPLIANCE_URL || "http://192.168.50.189:3010";
export const DEFAULT_ARTIFACT_DIR = process.env.GPU45_ARTIFACT_DIR || join(homedir(), ".codex", "gpu45-artifacts");
const MCP_TOKEN = process.env.GPU45_MCP_TOKEN || "";

const PROTOCOL_VERSION = "2024-11-05";

const tools = [
  {
    name: "gpu45_status",
    description: "Read current GPU45 appliance health, active model, telemetry, and media-service snapshots.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_image_generate",
    description: "Generate an image on the GPU45 appliance. The LLM service is stopped by the image service during GPU work and restarted afterward.",
    inputSchema: {
      type: "object",
      properties: {
        prompt: { type: "string", minLength: 1 },
        negative_prompt: { type: "string" },
        profile: { type: "string", default: "sdxl-turbo" },
        width: { type: "integer", minimum: 256, maximum: 1536, default: 1024 },
        height: { type: "integer", minimum: 256, maximum: 1536, default: 1024 },
        steps: { type: "integer", minimum: 1, maximum: 60 },
        guidance_scale: { type: "number" },
        seed: { type: "integer", default: -1 },
        wait: { type: "boolean", default: true },
        timeout_seconds: { type: "integer", minimum: 5, maximum: 1800, default: 600 },
        include_image: { type: "boolean", default: true },
      },
      required: ["prompt"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_video_generate",
    description: "Queue or run a video generation job on the GPU45 appliance and return job metadata plus the output URL when complete.",
    inputSchema: {
      type: "object",
      properties: {
        prompt: { type: "string", minLength: 1 },
        negative_prompt: { type: "string" },
        profile: { type: "string", default: "wan22-ti2v-5b" },
        size: { type: "string", default: "832*480" },
        steps: { type: "integer", minimum: 1, maximum: 24, default: 8 },
        duration_seconds: { type: "integer", minimum: 1, maximum: 15, default: 2 },
        seed: { type: "integer", default: -1 },
        wait: { type: "boolean", default: false },
        timeout_seconds: { type: "integer", minimum: 5, maximum: 7200, default: 3600 },
      },
      required: ["prompt"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_tts_synthesize",
    description: "Synthesize speech with Qwen3-TTS. Returns a local MP3 path and metadata. GPU mode, if enabled by the service, gets exclusive GPU access.",
    inputSchema: {
      type: "object",
      properties: {
        text: { type: "string", minLength: 1 },
        voice_id: { type: "string" },
        model_id: { type: "string" },
        use_default: { type: "boolean", default: true },
        output_name: { type: "string" },
      },
      required: ["text"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_tts_list_assets",
    description: "List Qwen3-TTS voices, trained voice models, and voice-generation jobs.",
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_tts_audiobook_create",
    description: "Upload a local EPUB/PDF/DOCX/TXT/HTML file to GPU45 and start chunked audiobook TTS. Chunks are available for preview as each completes.",
    inputSchema: {
      type: "object",
      properties: {
        file_path: { type: "string", minLength: 1 },
        model_id: { type: "string", minLength: 1 },
        title: { type: "string" },
        wait: { type: "boolean", default: false },
        timeout_seconds: { type: "integer", minimum: 5, maximum: 7200, default: 600 },
      },
      required: ["file_path", "model_id"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_tts_audiobook_get",
    description: "Get audiobook TTS job status, chunk states, preview URLs, and stitched output URL.",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string", minLength: 1 },
      },
      required: ["id"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_tts_audiobook_stop",
    description: "Request stop for an active audiobook TTS job. Current chunk may finish first; completed audio remains available.",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string", minLength: 1 },
      },
      required: ["id"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_tts_audiobook_resume",
    description: "Resume a stopped, failed, or review-needed audiobook TTS job from incomplete chunks.",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string", minLength: 1 },
      },
      required: ["id"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_job_get",
    description: "Get current metadata for an image, video, TTS, or Whisper job by kind and ID.",
    inputSchema: {
      type: "object",
      properties: {
        kind: { type: "string", enum: ["image", "video", "tts", "whisper"] },
        id: { type: "string", minLength: 1 },
      },
      required: ["kind", "id"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_web_search",
    description: "Search the public web through GPU45's local SearXNG backend and return normalized cached results.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", minLength: 1 },
        category: { type: "string", enum: ["general", "jobs"], default: "general" },
        limit: { type: "integer", minimum: 1, maximum: 25, default: 10 },
      },
      required: ["query"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_web_fetch",
    description: "Fetch a public http/https URL through GPU45, respecting SSRF guards, robots checks, rate limits, and extraction limits.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", minLength: 1 },
        render: { anyOf: [{ type: "boolean" }, { type: "string", enum: ["auto"] }], default: false },
        extract_links: { type: "boolean", default: true },
      },
      required: ["url"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_web_scrape",
    description: "Fetch and extract readable page content from a public URL. Use render='auto' for JS-heavy pages.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", minLength: 1 },
        render: { anyOf: [{ type: "boolean" }, { type: "string", enum: ["auto"] }], default: "auto" },
      },
      required: ["url"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_job_search",
    description: "Search official employer and ATS sources for job listings while rejecting common public job-board reposts.",
    inputSchema: {
      type: "object",
      properties: {
        query: { type: "string", minLength: 1 },
        remote_only: { type: "boolean", default: true },
        official_only: { type: "boolean", default: true },
        limit: { type: "integer", minimum: 1, maximum: 20, default: 10 },
      },
      required: ["query"],
      additionalProperties: false,
    },
  },
  {
    name: "gpu45_job_extract",
    description: "Extract structured job metadata from one official employer or ATS listing URL.",
    inputSchema: {
      type: "object",
      properties: {
        url: { type: "string", minLength: 1 },
        render: { anyOf: [{ type: "boolean" }, { type: "string", enum: ["auto"] }], default: "auto" },
      },
      required: ["url"],
      additionalProperties: false,
    },
  },
];

export function artifactUrl(baseUrl, route, id) {
  return `${baseUrl.replace(/\/$/, "")}${route}?id=${encodeURIComponent(id)}`;
}

export function summarizeJob(kind, job, baseUrl) {
  const status = job?.status ?? "unknown";
  const summary = { kind, status, id: job?.id ?? null, job };
  if (kind === "image" && job?.id && status === "completed") {
    summary.url = artifactUrl(baseUrl, "/api/images/output", job.id);
  }
  if (kind === "video" && job?.id && status === "completed") {
    summary.url = artifactUrl(baseUrl, "/api/video/output", job.id);
  }
  if (kind === "whisper" && job?.id && status === "completed") {
    summary.url = artifactUrl(baseUrl, "/api/whisper/output", job.id);
  }
  return summary;
}

function safeFileStem(value) {
  return String(value || "gpu45-artifact").replace(/[^a-z0-9_.-]+/gi, "-").replace(/^-+|-+$/g, "").slice(0, 80) || "gpu45-artifact";
}

function authenticatedHeaders(headers = {}) {
  return {
    ...(MCP_TOKEN ? { Authorization: `Bearer ${MCP_TOKEN}` } : {}),
    ...headers,
  };
}

async function fetchJson(url, init) {
  const response = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authenticatedHeaders(init?.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
  return await response.json();
}

async function fetchBytes(url, init) {
  const response = await fetch(url, { ...init, headers: authenticatedHeaders(init?.headers || {}) });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  }
  return {
    bytes: Buffer.from(await response.arrayBuffer()),
    contentType: response.headers.get("content-type") || "application/octet-stream",
  };
}

async function fetchFirstSseData(url, timeoutMs = 6000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal, headers: authenticatedHeaders() });
    if (!response.ok || !response.body) {
      throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const eventEnd = buffer.indexOf("\n\n");
      if (eventEnd >= 0) {
        await reader.cancel();
        const event = buffer.slice(0, eventEnd);
        const dataLine = event.split(/\r?\n/).find((line) => line.startsWith("data: "));
        if (!dataLine) return null;
        return JSON.parse(dataLine.slice(6));
      }
    }
    return null;
  } finally {
    clearTimeout(timeout);
    controller.abort();
  }
}

async function waitForJob({ baseUrl, kind, id, terminalStatuses, timeoutSeconds }) {
  const started = Date.now();
  while (Date.now() - started < timeoutSeconds * 1000) {
    const job = await getJob(baseUrl, kind, id);
    if (terminalStatuses.includes(job?.status)) return job;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error(`Timed out waiting for ${kind} job ${id}`);
}

async function getJob(baseUrl, kind, id) {
  if (kind === "image") {
    const snapshot = await fetchJson(`${baseUrl}/api/images`);
    return snapshot.jobs?.find((job) => job.id === id) || null;
  }
  if (kind === "video") {
    const snapshot = await fetchJson(`${baseUrl}/api/video`);
    return snapshot.jobs?.find((job) => job.id === id) || null;
  }
  if (kind === "tts") {
    const snapshot = await fetchJson(`${baseUrl}/api/tts`);
    return snapshot.voiceJobs?.find((job) => job.id === id) || snapshot.models?.find((job) => job.id === id) || null;
  }
  if (kind === "whisper") {
    const snapshot = await fetchJson(`${baseUrl}/api/whisper`);
    return snapshot.jobs?.find((job) => job.id === id) || null;
  }
  throw new Error(`Unsupported job kind: ${kind}`);
}

function textContent(value) {
  return [{ type: "text", text: typeof value === "string" ? value : JSON.stringify(value, null, 2) }];
}

async function toolStatus(baseUrl) {
  const [live, images, video, tts, whisper] = await Promise.allSettled([
    fetchFirstSseData(`${baseUrl}/api/live`),
    fetchJson(`${baseUrl}/api/images`),
    fetchJson(`${baseUrl}/api/video`),
    fetchJson(`${baseUrl}/api/tts`),
    fetchJson(`${baseUrl}/api/whisper`),
  ]);
  return {
    appliance: baseUrl,
    live: live.status === "fulfilled" ? live.value : { error: live.reason.message },
    images: images.status === "fulfilled" ? images.value : { error: images.reason.message },
    video: video.status === "fulfilled" ? video.value : { error: video.reason.message },
    tts: tts.status === "fulfilled" ? tts.value : { error: tts.reason.message },
    whisper: whisper.status === "fulfilled" ? whisper.value : { error: whisper.reason.message },
  };
}

async function toolImageGenerate(baseUrl, args) {
  const payload = {
    action: "createJob",
    prompt: args.prompt,
    negative_prompt: args.negative_prompt || undefined,
    profile: args.profile || "sdxl-turbo",
    width: args.width || 1024,
    height: args.height || 1024,
    steps: args.steps,
    guidance_scale: args.guidance_scale,
    seed: Number.isInteger(args.seed) ? args.seed : -1,
  };
  const created = await fetchJson(`${baseUrl}/api/images`, { method: "POST", body: JSON.stringify(payload) });
  let job = created.job;
  if (args.wait !== false) {
    job = await waitForJob({
      baseUrl,
      kind: "image",
      id: job.id,
      terminalStatuses: ["completed", "failed"],
      timeoutSeconds: args.timeout_seconds || 600,
    });
  }
  const summary = summarizeJob("image", job, baseUrl);
  const content = textContent(summary);
  if (job?.status === "completed" && args.include_image !== false) {
    const output = await fetchBytes(summary.url);
    content.push({ type: "image", data: output.bytes.toString("base64"), mimeType: output.contentType });
    await saveArtifact(`${safeFileStem(job.profile || "image")}-${job.id}.png`, output.bytes);
    summary.local_path = join(DEFAULT_ARTIFACT_DIR, `${safeFileStem(job.profile || "image")}-${job.id}.png`);
    content[0].text = JSON.stringify(summary, null, 2);
  }
  return content;
}

async function toolVideoGenerate(baseUrl, args) {
  const payload = {
    action: "createJob",
    prompt: args.prompt,
    negative_prompt: args.negative_prompt || undefined,
    profile: args.profile || "wan22-ti2v-5b",
    size: args.size || "832*480",
    steps: args.steps || 8,
    duration_seconds: args.duration_seconds || 2,
    seed: Number.isInteger(args.seed) ? args.seed : -1,
  };
  const created = await fetchJson(`${baseUrl}/api/video`, { method: "POST", body: JSON.stringify(payload) });
  let job = created.job;
  if (args.wait === true) {
    job = await waitForJob({
      baseUrl,
      kind: "video",
      id: job.id,
      terminalStatuses: ["completed", "failed", "cancelled"],
      timeoutSeconds: args.timeout_seconds || 3600,
    });
  }
  return textContent(summarizeJob("video", job, baseUrl));
}

async function toolTtsSynthesize(baseUrl, args) {
  const selectors = [args.voice_id, args.model_id, args.use_default !== false ? true : undefined].filter(Boolean);
  if (selectors.length !== 1) {
    throw new Error("Specify exactly one of voice_id, model_id, or use_default=true.");
  }
  const response = await fetchBytes(`${baseUrl}/api/tts`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: "synthesize",
      text: args.text,
      voiceId: args.voice_id,
      modelId: args.model_id,
      useDefault: args.use_default !== false,
    }),
  });
  const fileName = `${safeFileStem(args.output_name || "tts")}-${Date.now()}.mp3`;
  const localPath = await saveArtifact(fileName, response.bytes);
  return textContent({
    kind: "tts",
    status: "completed",
    content_type: response.contentType,
    bytes: response.bytes.length,
    local_path: localPath,
  });
}

function audiobookSummary(job, baseUrl) {
  if (!job) return null;
  const copy = { ...job };
  copy.stitched_url = `${baseUrl}/api/tts/audiobook/audio?id=${encodeURIComponent(job.id)}`;
  copy.chunks = (job.chunks || []).map((chunk) => ({
    ...chunk,
    preview_url: `${baseUrl}/api/tts/audiobook/audio?id=${encodeURIComponent(job.id)}&chunk=${encodeURIComponent(chunk.index)}`,
  }));
  return copy;
}

async function toolTtsAudiobookCreate(baseUrl, args) {
  const bytes = await readFile(args.file_path);
  const form = new FormData();
  form.set("action", "createAudiobook");
  form.set("model_id", args.model_id);
  if (args.title) form.set("title", args.title);
  form.set("file", new Blob([bytes]), basename(args.file_path));
  const response = await fetch(`${baseUrl}/api/tts`, { method: "POST", body: form, headers: authenticatedHeaders() });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  const created = await response.json();
  let job = created.job;
  if (args.wait === true && job?.id) {
    const started = Date.now();
    while (Date.now() - started < (args.timeout_seconds || 600) * 1000) {
      const snapshot = await fetchJson(`${baseUrl}/api/tts`);
      job = snapshot.audiobookJobs?.find((item) => item.id === job.id) || job;
      if (["completed", "failed", "stopped", "needs_review"].includes(job?.status)) break;
      await new Promise((resolve) => setTimeout(resolve, 3000));
    }
  }
  return audiobookSummary(job, baseUrl);
}

async function toolTtsAudiobookGet(baseUrl, args) {
  const snapshot = await fetchJson(`${baseUrl}/api/tts`);
  const job = snapshot.audiobookJobs?.find((item) => item.id === args.id);
  if (!job) throw new Error(`Audiobook job not found: ${args.id}`);
  return audiobookSummary(job, baseUrl);
}

async function toolTtsAudiobookAction(baseUrl, id, action) {
  const response = await fetchJson(`${baseUrl}/api/tts`, {
    method: "POST",
    body: JSON.stringify({ action, id }),
  });
  return audiobookSummary(response.job, baseUrl);
}

async function toolWebSearch(baseUrl, args) {
  const params = new URLSearchParams({
    q: args.query,
    category: args.category || "general",
    limit: String(args.limit || 10),
  });
  return await fetchJson(`${baseUrl}/api/web/search?${params}`);
}

async function toolWebFetch(baseUrl, args) {
  return await fetchJson(`${baseUrl}/api/web/fetch`, {
    method: "POST",
    body: JSON.stringify({
      url: args.url,
      render: args.render ?? false,
      extractLinks: args.extract_links !== false,
    }),
  });
}

async function toolWebScrape(baseUrl, args) {
  return await fetchJson(`${baseUrl}/api/web/fetch`, {
    method: "POST",
    body: JSON.stringify({
      url: args.url,
      render: args.render ?? "auto",
      extractLinks: true,
    }),
  });
}

async function toolJobSearch(baseUrl, args) {
  return await fetchJson(`${baseUrl}/api/web/jobs/search`, {
    method: "POST",
    body: JSON.stringify({
      query: args.query,
      remoteOnly: args.remote_only !== false,
      officialOnly: args.official_only !== false,
      limit: args.limit || 10,
    }),
  });
}

async function toolJobExtract(baseUrl, args) {
  return await fetchJson(`${baseUrl}/api/web/jobs/extract`, {
    method: "POST",
    body: JSON.stringify({
      url: args.url,
      render: args.render ?? "auto",
    }),
  });
}

async function saveArtifact(fileName, bytes) {
  await mkdir(DEFAULT_ARTIFACT_DIR, { recursive: true });
  const path = join(DEFAULT_ARTIFACT_DIR, fileName);
  await writeFile(path, bytes);
  return path;
}

async function callTool(name, args = {}, baseUrl = DEFAULT_BASE_URL) {
  if (name === "gpu45_status") return textContent(await toolStatus(baseUrl));
  if (name === "gpu45_image_generate") return await toolImageGenerate(baseUrl, args);
  if (name === "gpu45_video_generate") return await toolVideoGenerate(baseUrl, args);
  if (name === "gpu45_tts_synthesize") return await toolTtsSynthesize(baseUrl, args);
  if (name === "gpu45_tts_list_assets") return textContent((await fetchJson(`${baseUrl}/api/tts`)));
  if (name === "gpu45_tts_audiobook_create") return textContent(await toolTtsAudiobookCreate(baseUrl, args));
  if (name === "gpu45_tts_audiobook_get") return textContent(await toolTtsAudiobookGet(baseUrl, args));
  if (name === "gpu45_tts_audiobook_stop") return textContent(await toolTtsAudiobookAction(baseUrl, args.id, "stopAudiobook"));
  if (name === "gpu45_tts_audiobook_resume") return textContent(await toolTtsAudiobookAction(baseUrl, args.id, "resumeAudiobook"));
  if (name === "gpu45_job_get") return textContent(summarizeJob(args.kind, await getJob(baseUrl, args.kind, args.id), baseUrl));
  if (name === "gpu45_web_search") return textContent(await toolWebSearch(baseUrl, args));
  if (name === "gpu45_web_fetch") return textContent(await toolWebFetch(baseUrl, args));
  if (name === "gpu45_web_scrape") return textContent(await toolWebScrape(baseUrl, args));
  if (name === "gpu45_job_search") return textContent(await toolJobSearch(baseUrl, args));
  if (name === "gpu45_job_extract") return textContent(await toolJobExtract(baseUrl, args));
  throw new Error(`Unknown tool: ${name}`);
}

export async function handleJsonRpc(message, baseUrl = DEFAULT_BASE_URL) {
  if (!message || typeof message !== "object") return null;
  if (message.id === undefined) return null;

  try {
    if (message.method === "initialize") {
      return {
        jsonrpc: "2.0",
        id: message.id,
        result: {
          protocolVersion: PROTOCOL_VERSION,
          capabilities: { tools: {} },
          serverInfo: { name: "gpu45-appliance", version: "0.1.0" },
        },
      };
    }
    if (message.method === "tools/list") {
      return { jsonrpc: "2.0", id: message.id, result: { tools } };
    }
    if (message.method === "tools/call") {
      const result = await callTool(message.params?.name, message.params?.arguments || {}, baseUrl);
      return { jsonrpc: "2.0", id: message.id, result: { content: result } };
    }
    return { jsonrpc: "2.0", id: message.id, error: { code: -32601, message: `Method not found: ${message.method}` } };
  } catch (error) {
    return {
      jsonrpc: "2.0",
      id: message.id,
      error: { code: -32000, message: error instanceof Error ? error.message : String(error) },
    };
  }
}

async function main() {
  const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of rl) {
    if (!line.trim()) continue;
    let response;
    try {
      response = await handleJsonRpc(JSON.parse(line));
    } catch (error) {
      response = { jsonrpc: "2.0", id: null, error: { code: -32700, message: error instanceof Error ? error.message : String(error) } };
    }
    if (response) process.stdout.write(`${JSON.stringify(response)}\n`);
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error);
    process.exit(1);
  });
}
