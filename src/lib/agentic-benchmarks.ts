import { getConfig } from "./config";

export type AgenticQualification = {
  profile_name: string;
  profile_hash: string;
  status: "pending" | "queued" | "running" | "eligible" | "failed" | "interrupted";
  remediation?: string | null;
  last_checked_at?: string | null;
};

export type AgenticModel = {
  name: string;
  description?: string;
  servedAlias?: string;
  backend?: string;
  ctxSize?: number;
  modelSizeBytes?: number;
  profileHash: string;
  qualification?: AgenticQualification;
};

export type AgenticSuite = {
  id: string;
  name: string;
  version: string;
  track: string;
  taskCount?: number | null;
  requiresDocker: boolean;
  manifestHash: string;
};

export type AgenticCampaign = {
  id: string;
  name: string;
  preset: string;
  status: string;
  phase: string;
  runSummary?: Record<string, number>;
  created_at: string;
  updated_at: string;
};

export type AgenticCampaignDetail = {
  campaign: AgenticCampaign & { current_run_id?: string | null; error?: string | null };
  runs: Array<Record<string, string | number | null>>;
  ranking: Array<Record<string, unknown>>;
  events: Array<Record<string, string | number | null>>;
};

async function agenticFetch(path: string, init?: RequestInit): Promise<unknown> {
  const cfg = getConfig();
  if (!cfg.agenticToken) throw new Error("Agentic benchmark coordinator token is not configured");
  const response = await fetch(`${cfg.agenticUrl}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.agenticToken}`, ...init?.headers },
    cache: "no-store",
    signal: AbortSignal.timeout(30_000),
  });
  const payload = await response.json().catch(() => ({ error: `Coordinator returned HTTP ${response.status}` }));
  if (!response.ok) throw new Error(String((payload as { error?: string }).error || `Coordinator returned HTTP ${response.status}`));
  return payload;
}

export async function listAgenticModels(): Promise<AgenticModel[]> {
  return ((await agenticFetch("/v1/models")) as { models: AgenticModel[] }).models;
}

export async function listAgenticSuites(): Promise<AgenticSuite[]> {
  return ((await agenticFetch("/v1/suites")) as { suites: AgenticSuite[] }).suites;
}

export async function listAgenticCampaigns(): Promise<AgenticCampaign[]> {
  return ((await agenticFetch("/v1/campaigns")) as { campaigns: AgenticCampaign[] }).campaigns;
}

export async function createAgenticCampaign(body: unknown): Promise<{ id: string }> {
  return (await agenticFetch("/v1/campaigns", { method: "POST", body: JSON.stringify(body) })) as { id: string };
}

export async function getAgenticCampaign(id: string): Promise<AgenticCampaignDetail> {
  return (await agenticFetch(`/v1/campaigns/${encodeURIComponent(id)}`)) as AgenticCampaignDetail;
}

export async function agenticCampaignAction(id: string, action: string): Promise<{ ok: boolean }> {
  return (await agenticFetch(`/v1/campaigns/${encodeURIComponent(id)}/action`, { method: "POST", body: JSON.stringify({ action }) })) as { ok: boolean };
}

export async function agenticModelSmoke(profileName: string): Promise<{ ok: boolean }> {
  return (await agenticFetch(`/v1/models/${encodeURIComponent(profileName)}/smoke`, { method: "POST", body: "{}" })) as { ok: boolean };
}

export async function listAgenticTasks(id: string, cursor = 0, limit = 50): Promise<unknown> {
  return agenticFetch(`/v1/campaigns/${encodeURIComponent(id)}/tasks?cursor=${cursor}&limit=${limit}`);
}
