"use client";

import { ArchiveRestore, CloudOff, LoaderCircle, Play, ShieldCheck } from "lucide-react";
import { useState } from "react";
import type { BackupStatus } from "@/lib/backups";
import { StatusBadge } from "./status-badge";

export function BackupPanel({ initial }: { initial: BackupStatus }) {
  const [status, setStatus] = useState(initial);
  const [working, setWorking] = useState<"run" | "verify" | null>(null);
  const [error, setError] = useState("");

  async function start(action: "run" | "verify") {
    setWorking(action); setError("");
    try {
      const response = await fetch(`/api/backups/${action}`, { method: "POST" });
      const payload = await response.json() as { error?: string };
      if (!response.ok) throw new Error(payload.error ?? "Backup operation failed to start.");
      setStatus({ ...status, operation: action, status: "running", message: `${action} requested`, startedAt: new Date().toISOString(), finishedAt: null });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Backup operation failed to start.");
    } finally {
      setWorking(null);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2"><StatusBadge tone={status.status === "completed" ? "success" : status.status === "failed" ? "danger" : status.status === "running" ? "info" : "neutral"}>{status.status}</StatusBadge><span className="text-xs text-[#8a98aa]">{status.message}</span></div>
      <div className="rounded-md border border-[#223044] bg-[#0d131c] p-3 text-xs text-[#8a98aa]"><div className="font-mono text-[#cbd5e1]">{status.repository}</div><div className="mt-1">Last finished: {status.finishedAt ? new Date(status.finishedAt).toLocaleString() : "never"}</div></div>
      {!status.externalConfigured ? <div className="flex gap-2 rounded-md border border-[#fbbf24]/30 bg-[#fbbf24]/10 p-3 text-sm text-amber-100"><CloudOff className="mt-0.5 h-4 w-4 shrink-0" /><span>Local encrypted backups are enabled. Configure `GPU45_BACKUP_TARGET` for protection from disk failure.</span></div> : <div className="flex gap-2 text-sm text-emerald-200"><ShieldCheck className="h-4 w-4" />External backup target configured.</div>}
      {error ? <p className="text-sm text-rose-200">{error}</p> : null}
      <div className="flex gap-2"><button onClick={() => void start("run")} disabled={working !== null || status.status === "running"} className="inline-flex items-center gap-2 rounded-md border border-cyan-400/30 bg-cyan-400/10 px-3 py-2 text-sm text-cyan-100 disabled:opacity-50">{working === "run" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}Run backup</button><button onClick={() => void start("verify")} disabled={working !== null || status.status === "running"} className="inline-flex items-center gap-2 rounded-md border border-[#223044] bg-[#121a26] px-3 py-2 text-sm text-[#cbd5e1] disabled:opacity-50">{working === "verify" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ArchiveRestore className="h-4 w-4" />}Verify</button></div>
    </div>
  );
}
