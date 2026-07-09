import { promises as fs } from "node:fs";
import { runHostCommand } from "./proxmox";

export type BackupStatus = {
  operation: string;
  status: "never" | "running" | "completed" | "failed";
  message: string;
  startedAt: string | null;
  finishedAt: string | null;
  repository: string;
  externalConfigured: boolean;
  externalTarget: string | null;
};

const STATUS_PATH = "/var/lib/gpu45/backups/status.json";

export async function getBackupStatus(): Promise<BackupStatus> {
  try {
    return JSON.parse(await fs.readFile(STATUS_PATH, "utf8")) as BackupStatus;
  } catch {
    return { operation: "none", status: "never", message: "No backup has run yet.", startedAt: null, finishedAt: null, repository: "/models/appliance-backups/restic", externalConfigured: false, externalTarget: null };
  }
}

export async function startBackupOperation(operation: "backup" | "verify"): Promise<void> {
  const unit = operation === "backup" ? "gpu45-backup.service" : "gpu45-backup-verify.service";
  const output = await runHostCommand(`systemctl start --no-block ${unit}`);
  if (output === null) throw new Error(`Could not start ${operation}.`);
}
