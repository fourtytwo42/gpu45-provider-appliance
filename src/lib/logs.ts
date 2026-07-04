import { getConfig } from "./config";
import { runHostCommand } from "./proxmox";
import { shQuote } from "./command";

export const logSources = {
  provider: () => getConfig().providerService,
  proxy: () => "gpu45-responses-proxy.service",
  app: () => "gpu45-appliance.service",
  worker: () => "gpu45-appliance-worker.service",
  fan: () => getConfig().fanService,
} as const;

export type LogSource = keyof typeof logSources;

export function isLogSource(value: string): value is LogSource {
  return value in logSources;
}

export async function readServiceLogs(source: LogSource, limit = 200): Promise<string[]> {
  const safeLimit = Math.max(20, Math.min(1000, Math.round(limit)));
  const service = logSources[source]();
  const output = await runHostCommand(
    `journalctl -u ${shQuote(service)} -n ${safeLimit} --no-pager --output=short-iso`,
  );
  return (output ?? "").split(/\r?\n/).filter(Boolean);
}
