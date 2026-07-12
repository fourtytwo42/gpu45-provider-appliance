import { getUnifiedJobs } from "@/lib/jobs";
import { collectLiveTelemetry } from "@/lib/live-telemetry";
import { getPocketTtsSnapshot } from "@/lib/pocket-tts";
import { getResourceState } from "@/lib/resource-manager";
import { getTtsSnapshot } from "@/lib/tts";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Topic = "telemetry" | "provider" | "resources" | "jobs" | "tts" | "pocket-tts";
const DEFAULT_TOPICS: Topic[] = ["telemetry", "resources", "jobs"];
const VALID_TOPICS = new Set<Topic>([...DEFAULT_TOPICS, "provider", "tts", "pocket-tts"]);

function requestedTopics(request: Request): Topic[] {
  const values = new URL(request.url).searchParams.get("topics")?.split(",") ?? DEFAULT_TOPICS;
  const topics = values.map((value) => value.trim() as Topic).filter((value) => VALID_TOPICS.has(value));
  return topics.length > 0 ? [...new Set(topics)] : DEFAULT_TOPICS;
}

async function readTopic(topic: Topic): Promise<unknown> {
  if (topic === "telemetry") return collectLiveTelemetry();
  if (topic === "provider") return (await collectLiveTelemetry()).provider;
  if (topic === "resources") return getResourceState();
  if (topic === "jobs") return getUnifiedJobs();
  if (topic === "tts") return getTtsSnapshot();
  return getPocketTtsSnapshot();
}

export async function GET(request: Request): Promise<Response> {
  const encoder = new TextEncoder();
  const topics = requestedTopics(request);
  let revision = Math.max(0, Number(request.headers.get("last-event-id") ?? 0) || 0);
  const previous = new Map<Topic, string>();

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      let closed = false;
      let lastHeartbeat = Date.now();
      const close = () => {
        if (closed) return;
        closed = true;
        try { controller.close(); } catch { /* Client already disconnected. */ }
      };
      request.signal.addEventListener("abort", close, { once: true });

      void (async () => {
        while (!closed) {
          const snapshots = await Promise.all(topics.map(async (topic) => {
            try {
              return { topic, payload: await readTopic(topic), error: null };
            } catch (error) {
              return { topic, payload: null, error: error instanceof Error ? error.message : `${topic} update failed` };
            }
          }));
          for (const snapshot of snapshots) {
            if (closed) break;
            const serialized = JSON.stringify(snapshot.error ? { error: snapshot.error } : snapshot.payload);
            if (previous.get(snapshot.topic) === serialized) continue;
            previous.set(snapshot.topic, serialized);
            revision += 1;
            controller.enqueue(encoder.encode(`id: ${revision}\nevent: ${snapshot.topic}\ndata: ${serialized}\n\n`));
          }
          if (!closed && Date.now() - lastHeartbeat >= 15_000) {
            revision += 1;
            controller.enqueue(encoder.encode(`id: ${revision}\nevent: heartbeat\ndata: {"revision":${revision}}\n\n`));
            lastHeartbeat = Date.now();
          }
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      })().catch(close);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
