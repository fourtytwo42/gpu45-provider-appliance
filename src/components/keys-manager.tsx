"use client";

import { useState } from "react";
import { Ban, Copy, KeyRound, Play, Plus, Trash2 } from "lucide-react";
import type { ApiKeyRecord } from "@/lib/types";

export function KeysManager({ initialKeys, initialAllowAnonymous }: { initialKeys: ApiKeyRecord[]; initialAllowAnonymous: boolean }) {
  const [keys, setKeys] = useState(initialKeys);
  const [allowAnonymous, setAllowAnonymousState] = useState(initialAllowAnonymous);
  const [name, setName] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [revealed, setRevealed] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  async function refresh() {
    const response = await fetch("/api/keys", { cache: "no-store" });
    if (response.ok) setKeys((await response.json()).keys);
  }
  async function create() {
    const response = await fetch("/api/keys", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name || undefined, expiresAt: expiresAt ? new Date(expiresAt).toISOString() : null }) });
    const payload = await response.json();
    if (!response.ok) return setMessage(payload.error ?? "Unable to create key");
    setRevealed(payload.key); setName(""); setExpiresAt(""); setMessage("Key created. It is shown only once."); await refresh();
  }
  async function toggleAnonymous(next: boolean) {
    const response = await fetch("/api/keys", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ allowAnonymous: next }) });
    if (response.ok) setAllowAnonymousState(next);
  }
  async function suspend(id: string, suspended: boolean) {
    await fetch("/api/keys", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, suspended }) }); await refresh();
  }
  async function remove(id: string) {
    if (!confirm("Delete this API key? Existing clients using it will stop working.")) return;
    await fetch(`/api/keys?id=${encodeURIComponent(id)}`, { method: "DELETE" }); await refresh();
  }

  return <div className="space-y-5">
    <section className="border border-white/10 bg-[#0a1119] p-4">
      <div className="flex flex-wrap items-center justify-between gap-4"><div><h1 className="text-lg font-semibold text-white">API keys</h1><p className="mt-1 text-sm text-slate-500">Issue credentials and monitor model traffic by client.</p></div><label className="flex cursor-pointer items-center gap-3 border border-white/10 bg-[#070c12] px-3 py-2"><span className="text-sm text-slate-300">Allow requests without a key</span><input type="checkbox" checked={allowAnonymous} onChange={(event) => void toggleAnonymous(event.target.checked)} className="h-4 w-4 accent-cyan-400" /></label></div>
      <div className="mt-4 grid gap-2 md:grid-cols-[1fr_240px_auto]"><input value={name} onChange={(event) => setName(event.target.value)} placeholder="Key name (optional)" className="border border-white/10 bg-[#05090e] px-3 py-2 text-sm outline-none focus:border-cyan-400/50" /><input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} className="border border-white/10 bg-[#05090e] px-3 py-2 text-sm text-slate-300 outline-none focus:border-cyan-400/50" /><button onClick={() => void create()} className="inline-flex items-center justify-center gap-2 border border-cyan-400/30 bg-cyan-400/10 px-4 py-2 text-sm text-cyan-200"><Plus className="h-4 w-4" />Create key</button></div>
      {revealed ? <div className="mt-3 flex items-center gap-2 border border-amber-400/30 bg-amber-400/10 p-3"><KeyRound className="h-4 w-4 text-amber-300" /><code className="min-w-0 flex-1 break-all text-sm text-amber-100">{revealed}</code><button title="Copy key" onClick={() => void navigator.clipboard.writeText(revealed)} className="p-2 text-amber-200 hover:bg-white/10"><Copy className="h-4 w-4" /></button></div> : null}
      {message ? <p className="mt-2 text-xs text-slate-400">{message}</p> : null}
    </section>
    <section className="border border-white/10 bg-[#0a1119] p-4"><div className="flex items-center justify-between"><h2 className="text-sm font-semibold text-white">Issued keys</h2><span className="font-mono text-xs text-slate-500">{keys.length} total</span></div><div className="mt-3 divide-y divide-white/10 border-y border-white/10">{keys.length === 0 ? <div className="py-8 text-center text-sm text-slate-500">No managed keys yet. Anonymous access is {allowAnonymous ? "enabled" : "disabled"}.</div> : keys.map((key) => { const expired = key.expiresAt ? new Date(key.expiresAt) <= new Date() : false; const blocked = Boolean(key.suspendedAt) || expired; return <div key={key.id} className="grid gap-3 py-4 lg:grid-cols-[1.1fr_.9fr_1fr_auto] lg:items-center"><div><div className="flex items-center gap-2"><span className="font-medium text-white">{key.name || "Unnamed key"}</span><span className={`border px-1.5 py-0.5 text-[10px] uppercase ${blocked ? "border-rose-400/30 text-rose-300" : "border-emerald-400/30 text-emerald-300"}`}>{expired ? "expired" : key.suspendedAt ? "suspended" : "active"}</span></div><div className="mt-1 font-mono text-xs text-slate-500">{key.keyPrefix}</div><div className="mt-1 text-[11px] text-slate-600">Expires {key.expiresAt ? new Date(key.expiresAt).toLocaleString("en-US", { timeZone: "America/Chicago" }) : "never"}</div></div><div className="grid grid-cols-3 gap-3 text-xs"><div><div className="font-mono text-white">{key.requestCount.toLocaleString()}</div><div className="text-slate-600">requests</div></div><div><div className="font-mono text-white">{key.promptTokens.toLocaleString()}</div><div className="text-slate-600">input</div></div><div><div className="font-mono text-white">{key.completionTokens.toLocaleString()}</div><div className="text-slate-600">output</div></div></div><div className="text-xs text-slate-400">{key.models.length ? key.models.map((model) => <div key={model.model} className="flex justify-between gap-3"><span className="truncate">{model.model}</span><span className="font-mono text-slate-600">{model.requests} req</span></div>) : <span className="text-slate-600">No usage recorded</span>}<div className="mt-1 text-[11px] text-slate-600">Last used {key.lastUsedAt ? new Date(key.lastUsedAt).toLocaleString("en-US", { timeZone: "America/Chicago" }) : "never"}</div></div><div className="flex gap-1">{key.suspendedAt ? <button title="Reactivate key" onClick={() => void suspend(key.id, false)} className="p-2 text-emerald-300 hover:bg-emerald-400/10"><Play className="h-4 w-4" /></button> : <button title="Suspend key" onClick={() => void suspend(key.id, true)} className="p-2 text-amber-300 hover:bg-amber-400/10"><Ban className="h-4 w-4" /></button>}<button title="Delete key" onClick={() => void remove(key.id)} className="p-2 text-rose-300 hover:bg-rose-400/10"><Trash2 className="h-4 w-4" /></button></div></div>; })}</div></section>
  </div>;
}
