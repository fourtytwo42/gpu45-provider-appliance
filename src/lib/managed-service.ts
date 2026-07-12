import { isLiveRuntime } from "./config";
import { touchResourceWorker } from "./resource-manager";

export type ManagedWorkerKind = "tts" | "image" | "video" | "whisper";

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export async function managedServiceFetch(
  kind: ManagedWorkerKind,
  url: string,
  init?: RequestInit,
  options: { wake?: boolean; startupTimeoutMs?: number } = {},
): Promise<Response> {
  const wake = options.wake === true && isLiveRuntime();
  if (wake) await touchResourceWorker(kind);
  const deadline = Date.now() + (options.startupTimeoutMs ?? 90_000);
  let lastError: unknown = null;
  do {
    try {
      return await fetch(url, { ...init, cache: "no-store" });
    } catch (error) {
      lastError = error;
      if (!wake) throw error;
      await sleep(500);
    }
  } while (Date.now() < deadline);
  throw lastError instanceof Error ? lastError : new Error(`${kind} worker did not become ready.`);
}
