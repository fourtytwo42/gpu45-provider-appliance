import { runBash, shQuote } from "./command";
import { getConfig } from "./config";
import { parsePrometheusSample } from "./parsers";
import { getResourceState } from "./resource-manager";
import type { ProviderProcessStatus, ProviderSnapshot, ProviderStatus } from "./types";

type ProviderStatusInput = {
  proxyReady: boolean;
  backendReady: boolean;
  processStatus: ProviderProcessStatus;
  activeRequests: number;
  resourceOwner: string | null;
  transition: ProviderSnapshot["transition"];
};

export function deriveProviderStatus(input: ProviderStatusInput): ProviderStatus {
  if (!input.proxyReady) return "failed";
  if (input.backendReady) return input.activeRequests > 0 ? "busy" : "ready";
  if (input.transition === "releasing") return "releasing";
  if (input.transition === "restoring") return "restoring";
  if (input.transition === "starting" || input.resourceOwner === "llm") return "starting";
  if (input.resourceOwner && input.resourceOwner !== "llm") return "unloaded";
  if (input.processStatus === "active" || input.processStatus === "activating") return "starting";
  if (input.processStatus === "failed") return "failed";
  return "unloaded";
}

async function fetchProbe<T>(url: string, parse: (response: Response) => Promise<T>): Promise<T | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 2_500);
  try {
    const response = await fetch(url, { cache: "no-store", signal: controller.signal });
    if (!response.ok) return null;
    return await parse(response);
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function extractModelId(response: unknown): string | null {
  const dataModel = (response as { data?: Array<{ id?: string; model?: string; name?: string }> } | null)?.data?.[0];
  if (dataModel?.id) return dataModel.id;
  if (dataModel?.model) return dataModel.model;
  if (dataModel?.name) return dataModel.name;
  const modelsModel = (response as { models?: Array<{ id?: string; model?: string; name?: string }> } | null)?.models?.[0];
  return modelsModel?.id ?? modelsModel?.model ?? modelsModel?.name ?? null;
}

function normalizeProcessStatus(value: string): ProviderProcessStatus {
  const status = value.trim() as ProviderProcessStatus;
  return ["active", "activating", "deactivating", "inactive", "failed"].includes(status) ? status : "unknown";
}

export async function collectProviderRuntimeSnapshot(): Promise<ProviderSnapshot> {
  const cfg = getConfig();
  const [backendModelsResponse, proxyModelsResponse, metricsText, processText, resources] = await Promise.all([
    fetchProbe(`${cfg.backendUrl}/v1/models`, (response) => response.json()),
    fetchProbe(`${cfg.providerUrl}/v1/models`, (response) => response.json()),
    fetchProbe(`${cfg.providerUrl}/metrics`, (response) => response.text()),
    runBash(`systemctl is-active ${shQuote(cfg.providerService)} 2>/dev/null || true`).catch(() => "unknown"),
    getResourceState(),
  ]);
  const metrics = parsePrometheusSample(metricsText ?? "", [
    "llamacpp:requests_processing",
    "llamacpp:prompt_tokens_total",
    "llamacpp:tokens_predicted_total",
    "llamacpp:prompt_tokens_seconds",
    "llamacpp:predicted_tokens_seconds",
  ]);
  const activeRequests = metrics["llamacpp:requests_processing"] ?? 0;
  const processStatus = normalizeProcessStatus(processText);
  const resourceOwner = resources.owner?.kind ?? null;
  const transition = resources.transition?.status ?? null;
  const proxyReady = proxyModelsResponse !== null;
  const backendReady = backendModelsResponse !== null;
  const status = deriveProviderStatus({ proxyReady, backendReady, processStatus, activeRequests, resourceOwner, transition });
  return {
    status,
    model: extractModelId(backendModelsResponse) ?? extractModelId(proxyModelsResponse) ?? "unknown",
    providerUrl: cfg.providerUrl,
    activeRequests,
    promptTokens: Math.round(metrics["llamacpp:prompt_tokens_total"] ?? 0),
    completionTokens: Math.round(metrics["llamacpp:tokens_predicted_total"] ?? 0),
    tokensPerSecond: metrics["llamacpp:predicted_tokens_seconds"] ?? 0,
    metrics,
    lastError: status === "failed" ? "Provider proxy or LLM process is unavailable." : null,
    processStatus,
    proxyReady,
    backendReady,
    resourceOwner,
    transition,
  };
}
