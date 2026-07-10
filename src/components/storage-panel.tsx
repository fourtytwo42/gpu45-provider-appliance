"use client";

import { Archive, HardDrive, LoaderCircle, RefreshCw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { formatBytes } from "@/lib/format";
import type { StorageItem } from "@/lib/storage";
import { StatusBadge } from "./status-badge";

type Inventory = { items: StorageItem[]; usedBytes: number; reclaimableBytes: number };

export function StoragePanel() {
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [working, setWorking] = useState(false);
  const [message, setMessage] = useState("");
  async function load() { setWorking(true); try { const response = await fetch("/api/storage", { cache: "no-store" }); setInventory(await response.json() as Inventory); } finally { setWorking(false); } }
  useEffect(() => {
    let cancelled = false;
    fetch("/api/storage", { cache: "no-store" })
      .then((response) => response.json() as Promise<Inventory>)
      .then((value) => { if (!cancelled) setInventory(value); })
      .finally(() => { if (!cancelled) setWorking(false); });
    return () => { cancelled = true; };
  }, []);
  async function quarantine() {
    if (!selected.length || !window.confirm(`Move ${selected.length} verified asset(s) to seven-day quarantine?`)) return;
    setWorking(true); setMessage("");
    try { const response = await fetch("/api/storage/quarantine", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ paths: selected }) }); const payload = await response.json() as { error?: string; reclaimedBytes?: number; operationId?: string }; if (!response.ok) throw new Error(payload.error); setMessage(`Quarantined ${formatBytes(payload.reclaimedBytes ?? 0)}. Restore id: ${payload.operationId}`); setSelected([]); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Quarantine failed."); }
    finally { setWorking(false); }
  }
  return <div className="space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-2"><div className="text-sm text-[#8a98aa]">{inventory ? `${formatBytes(inventory.usedBytes)} inventoried / ${formatBytes(inventory.reclaimableBytes)} eligible` : "Scanning managed storage"}</div><button title="Refresh storage inventory" onClick={() => void load()} disabled={working} className="rounded-md border border-[#223044] p-2 text-[#cbd5e1]">{working ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}</button></div>
    <div className="max-h-80 divide-y divide-[#223044] overflow-y-auto border border-[#223044]">{inventory?.items.map((item) => <label key={item.path} className="grid grid-cols-[auto_1fr_auto] items-center gap-3 bg-[#0d131c] p-3"><input type="checkbox" disabled={item.protected} checked={selected.includes(item.path)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, item.path] : current.filter((value) => value !== item.path))} aria-label={`Select ${item.name} for quarantine`} /><div className="min-w-0"><div className="flex items-center gap-2"><HardDrive className="h-4 w-4 text-[#21d4fd]" /><span className="truncate text-sm text-[#e6edf5]" title={item.path}>{item.name}</span>{item.protected ? <ShieldCheck className="h-3.5 w-3.5 text-[#36fba1]" /> : null}</div><div className="mt-1 truncate font-mono text-[10px] text-[#617083]">{item.path}</div></div><div className="text-right"><StatusBadge tone={item.classification === "production" ? "success" : item.protected ? "neutral" : "warning"}>{item.classification}</StatusBadge><div className="mt-1 font-mono text-xs text-[#8a98aa]">{formatBytes(item.sizeBytes)}</div></div></label>)}</div>
    {message ? <p className="text-xs text-[#cbd5e1]">{message}</p> : null}
    <button onClick={() => void quarantine()} disabled={working || !selected.length} className="inline-flex items-center gap-2 rounded-md border border-[#fbbf24]/30 bg-[#fbbf24]/10 px-3 py-2 text-sm text-amber-100 disabled:opacity-50"><Archive className="h-4 w-4" />Quarantine selected</button>
  </div>;
}
