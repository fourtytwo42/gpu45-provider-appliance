"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  Eye,
  EyeOff,
  LoaderCircle,
  Power,
  Save,
  Search,
  SlidersHorizontal,
  Star,
  Trash2,
  X,
} from "lucide-react";
import { formatBytes } from "@/lib/format";
import type { DownloadJob, LaunchProfile, ModelAsset } from "@/lib/types";
import type { HuggingFaceSearchResult } from "@/lib/huggingface";
import { classifyModelAsset } from "@/lib/model-assets";

const FINISHED = new Set(["completed", "failed", "cancelled"]);
const directory = (filePath: string) => filePath.replaceAll("\\", "/").split("/").slice(0, -1).join("/");

type ModelSettingsForm = {
  ctxSize: number;
  gpuLayers: string;
  batchSize: number;
  uBatchSize: number;
  cacheRamMiB: number;
  cacheTypeK: string;
  cacheTypeV: string;
  cacheReuse: number;
  specType: "none" | "draft-mtp";
  specDraftNMax: number;
  flashAttention: "on" | "off" | "auto";
  imageMinTokens: number;
  metrics: boolean;
  jinja: boolean;
};

function defaultSettings(model: ModelAsset): ModelSettingsForm {
  const profile = model.launchProfile;
  return {
    ctxSize: profile?.ctxSize ?? 262144,
    gpuLayers: profile?.gpuLayers ?? "all",
    batchSize: profile?.batchSize ?? 2048,
    uBatchSize: profile?.uBatchSize ?? 512,
    cacheRamMiB: profile?.cacheRamMiB ?? 8192,
    cacheTypeK: profile?.cacheTypeK ?? "q4_0",
    cacheTypeV: profile?.cacheTypeV ?? "q4_0",
    cacheReuse: profile?.cacheReuse ?? 1024,
    specType: (profile?.specType === "none" ? "none" : "draft-mtp"),
    specDraftNMax: profile?.specDraftNMax ?? 2,
    flashAttention: profile?.flashAttention === "off" || profile?.flashAttention === "auto" ? profile.flashAttention : "on",
    imageMinTokens: profile?.imageMinTokens ?? 1024,
    metrics: profile?.metrics ?? true,
    jinja: profile?.jinja ?? true,
  };
}

function settingsSummary(model: ModelAsset): string {
  const settings = defaultSettings(model);
  return `${settings.ctxSize.toLocaleString()} ctx · ${settings.gpuLayers} layers · b${settings.batchSize}/ub${settings.uBatchSize} · ${settings.cacheTypeK}/${settings.cacheTypeV}`;
}

export function ModelManager({ initialModels, diskFreeBytes }: { initialModels: ModelAsset[]; diskFreeBytes: number }) {
  const [models, setModels] = useState(initialModels);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<HuggingFaceSearchResult[]>([]);
  const [jobs, setJobs] = useState<DownloadJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [activatingPath, setActivatingPath] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [settingsPath, setSettingsPath] = useState<string | null>(null);
  const [savingSettingsPath, setSavingSettingsPath] = useState<string | null>(null);
  const [settingsForms, setSettingsForms] = useState<Record<string, ModelSettingsForm>>({});
  const [message, setMessage] = useState("");
  const lastCompleted = useRef<string | null>(null);

  const primaryModels = useMemo(() => models.filter((model) => classifyModelAsset(model.name) === "model"), [models]);
  const companionMap = useMemo(() => {
    const map = new Map(primaryModels.map((model) => [model.path, [] as ModelAsset[]]));
    const companions = models.filter((model) => classifyModelAsset(model.name) !== "model");
    for (const companion of companions) {
      const linked = primaryModels.find((model) => model.projectorPath === companion.path || model.draftPath === companion.path);
      const sameDirectory = primaryModels.filter((model) => directory(model.path) === directory(companion.path));
      const sameRepo = primaryModels.filter((model) => model.repo && model.repo === companion.repo);
      const active = primaryModels.find((model) => model.active && companion.active);
      const parent = linked ?? sameDirectory[0] ?? (sameRepo.length === 1 ? sameRepo[0] : null) ?? active;
      if (parent) map.get(parent.path)?.push(companion);
    }
    return map;
  }, [models, primaryModels]);

  const assigned = new Set([...companionMap.values()].flat().map((model) => model.path));
  const unattached = models.filter((model) => classifyModelAsset(model.name) !== "model" && !assigned.has(model.path));

  const loadJobs = useCallback(async () => {
    const response = await fetch("/api/downloads", { cache: "no-store" });
    if (!response.ok) return;
    const nextJobs = (await response.json()).jobs as DownloadJob[];
    setJobs(nextJobs);
    const completed = nextJobs.find((job) => job.status === "completed");
    if (completed && completed.id !== lastCompleted.current) {
      lastCompleted.current = completed.id;
      await refreshInventory();
    }
  }, []);

  useEffect(() => {
    const initial = setTimeout(() => void loadJobs(), 0);
    const timer = setInterval(() => void loadJobs(), 2500);
    return () => {
      clearTimeout(initial);
      clearInterval(timer);
    };
  }, [loadJobs]);

  async function refreshInventory() {
    const inventory = await fetch("/api/models", { cache: "no-store" });
    if (inventory.ok) setModels((await inventory.json()).models);
  }

  function openSettings(model: ModelAsset) {
    setSettingsPath((current) => current === model.path ? null : model.path);
    setSettingsForms((current) => ({ ...current, [model.path]: current[model.path] ?? defaultSettings(model) }));
  }

  function updateSettings(modelPath: string, values: Partial<ModelSettingsForm>) {
    setSettingsForms((current) => ({ ...current, [modelPath]: { ...current[modelPath], ...values } }));
  }

  async function saveSettings(model: ModelAsset) {
    const settings = settingsForms[model.path] ?? defaultSettings(model);
    setSavingSettingsPath(model.path);
    setMessage("");
    const response = await fetch("/api/models", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: model.path, settings }),
    });
    const payload = await response.json();
    setSavingSettingsPath(null);
    if (!response.ok) {
      setMessage(payload.error ?? "Unable to save model settings");
      return;
    }
    setMessage(`${model.name} settings saved.`);
    setModels((items) => items.map((item) => item.path === model.path ? { ...item, launchProfile: payload.profile as LaunchProfile } : item));
  }

  async function search() {
    if (!query.trim()) return;
    setBusy(true);
    setMessage("");
    const response = await fetch(`/api/huggingface/search?q=${encodeURIComponent(query)}`);
    const payload = await response.json();
    setBusy(false);
    if (!response.ok) return setMessage(payload.error ?? "Search failed");
    setResults(payload.results);
  }

  async function download(repoId: string, fileName: string) {
    const response = await fetch("/api/downloads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repoId, fileName, revision: "main" }),
    });
    const payload = await response.json();
    const count = Array.isArray(payload.companions) ? payload.companions.length : 0;
    setMessage(response.ok ? `${fileName} queued${count ? ` with ${count} MTP companion${count === 1 ? "" : "s"}` : ""}.` : payload.error ?? "Unable to queue download");
    await loadJobs();
  }

  async function clearJob(job?: DownloadJob) {
    const url = job ? `/api/downloads?id=${encodeURIComponent(job.id)}` : "/api/downloads?finished=true";
    const response = await fetch(url, { method: "DELETE" });
    const payload = await response.json();
    setMessage(response.ok ? `${payload.deleted} queue record${payload.deleted === 1 ? "" : "s"} removed. Model files were not changed.` : payload.error);
    await loadJobs();
  }

  async function remove(model: ModelAsset) {
    const primary = classifyModelAsset(model.name) === "model";
    if (!confirm(`Delete ${model.name} from disk?${primary ? " Attached MTP and projector files will also be deleted." : ""}`)) return;
    const response = await fetch("/api/models", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: model.path }),
    });
    const payload = await response.json();
    setMessage(payload.message ?? payload.error);
    if (response.ok) await refreshInventory();
  }

  async function activate(model: ModelAsset) {
    setActivatingPath(model.path);
    setMessage("");
    const response = await fetch("/api/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: model.path }),
    });
    const payload = await response.json();
    setMessage(payload.message ?? payload.error ?? "Activation failed");
    if (response.ok) await refreshInventory();
    setActivatingPath(null);
  }

  async function updateServing(model: ModelAsset, values: { served?: boolean; defaultModel?: boolean }) {
    const response = await fetch("/api/models", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: model.path, ...values }),
    });
    const payload = await response.json();
    if (!response.ok) return setMessage(payload.error ?? "Unable to update model catalog");
    setModels((items) => items.map((item) => item.path === model.path ? { ...item, ...values } : values.defaultModel ? { ...item, defaultModel: false } : item));
  }

  function CompanionRow({ model }: { model: ModelAsset }) {
    const role = classifyModelAsset(model.name);
    return (
      <div className="grid gap-2 border-t border-white/5 bg-[#060b10] px-3 py-2 md:grid-cols-[1fr_auto_auto] md:items-center">
        <div className="min-w-0 pl-6">
          <div className="flex items-center gap-2">
            <span className="truncate text-xs text-slate-300">{model.name}</span>
            <span className="border border-violet-400/30 bg-violet-400/10 px-1.5 py-0.5 text-[9px] uppercase text-violet-300">{role}</span>
          </div>
          <div className="truncate font-mono text-[10px] text-slate-700">{model.path}</div>
        </div>
        <span className="text-xs text-slate-500">{formatBytes(model.sizeBytes)}</span>
        <button disabled={model.active} title={`Delete ${role}`} onClick={() => void remove(model)} className="p-2 text-rose-300 hover:bg-rose-400/10 disabled:opacity-30">
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <section className="border border-white/10 bg-[#0a1119] p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-white">Model catalog</h1>
            <p className="mt-1 text-sm text-slate-500">Search compatible Hugging Face GGUF repositories and install an exact artifact.</p>
          </div>
          <div className="text-right text-xs text-slate-500">
            <div className="font-mono text-sm text-emerald-300">{formatBytes(diskFreeBytes)} free</div>
            <div>model storage</div>
          </div>
        </div>
        <form className="mt-4 flex gap-2" onSubmit={(event) => { event.preventDefault(); void search(); }}>
          <div className="relative min-w-0 flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Qwen 3.6 27B MTP GGUF" className="w-full border border-white/10 bg-[#060b10] py-2 pl-9 pr-3 text-sm outline-none focus:border-cyan-400/50" />
          </div>
          <button disabled={busy} className="inline-flex items-center gap-2 border border-cyan-400/30 bg-cyan-400/10 px-4 text-sm text-cyan-200 disabled:opacity-50">
            {busy ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
            Search
          </button>
        </form>
        <div className="mt-2 flex flex-wrap gap-2">
          {["lmstudio-community qwen gguf", "multimodal gguf", "unsloth MTP GGUF"].map((term) => (
            <button key={term} onClick={() => setQuery(term)} className="border border-white/10 px-2 py-1 text-xs text-slate-400 hover:border-cyan-400/30 hover:text-cyan-200">{term}</button>
          ))}
        </div>
        {message ? <div className="mt-3 border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-300">{message}</div> : null}
        <div className="mt-4 grid gap-3 xl:grid-cols-2">
          {results.map((result) => (
            <article key={result.repoId} className="border border-white/10 bg-[#070c12] p-3">
              <div className="flex justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate font-medium text-white">{result.repoId}</div>
                  <div className="mt-1 text-xs text-slate-500">{result.reason}</div>
                </div>
                {result.recommended ? <span className="h-fit shrink-0 border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-[11px] text-emerald-300">Recommended</span> : null}
              </div>
              <div className="mt-3 flex items-center gap-3 text-xs text-slate-500">
                <span>{result.ggufFiles.length} GGUF files</span>
                <span>{result.downloads.toLocaleString()} downloads</span>
              </div>
              {result.ggufFiles.length ? (
                <div className="mt-3 flex gap-2">
                  <select id={`file-${result.repoId}`} defaultValue={result.ggufFiles[0]} className="min-w-0 flex-1 border border-white/10 bg-[#05090e] px-2 py-2 text-xs text-slate-300">
                    {result.ggufFiles.map((file) => <option key={file}>{file}</option>)}
                  </select>
                  <button title="Queue selected file" onClick={() => { const select = document.getElementById(`file-${result.repoId}`) as HTMLSelectElement; void download(result.repoId, select.value); }} className="border border-emerald-400/30 bg-emerald-400/10 p-2 text-emerald-300">
                    <Download className="h-4 w-4" />
                  </button>
                </div>
              ) : <div className="mt-3 text-xs text-amber-300">No GGUF artifact was listed.</div>}
            </article>
          ))}
        </div>
      </section>

      {jobs.length ? (
        <section className="border border-white/10 bg-[#0a1119] p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Download queue</h2>
            <button disabled={!jobs.some((job) => FINISHED.has(job.status))} onClick={() => void clearJob()} className="inline-flex items-center gap-2 border border-white/10 px-3 py-1.5 text-xs text-slate-300 hover:border-rose-400/30 hover:text-rose-200 disabled:opacity-30">
              <Trash2 className="h-3.5 w-3.5" />
              Clear finished
            </button>
          </div>
          <div className="mt-3 space-y-2">
            {jobs.map((job) => {
              const pct = job.totalBytes > 0 ? Math.min(100, job.bytesDownloaded / job.totalBytes * 100) : 0;
              return (
                <div key={job.id} className="border border-white/10 bg-[#070c12] p-3">
                  <div className="flex items-center justify-between gap-3 text-sm">
                    <span className="truncate text-slate-200">{job.fileName}</span>
                    <div className="flex items-center gap-2">
                      <span className="capitalize text-slate-400">{job.status}</span>
                      <button disabled={job.status === "downloading"} title="Remove queue record only" onClick={() => void clearJob(job)} className="p-1.5 text-rose-300 hover:bg-rose-400/10 disabled:opacity-30">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                  <div className="mt-2 h-1.5 bg-white/10">
                    <div className={`h-full ${job.status === "failed" ? "bg-rose-400" : job.status === "completed" ? "bg-emerald-400" : "bg-cyan-400"}`} style={{ width: `${job.status === "completed" ? 100 : pct}%` }} />
                  </div>
                  <div className="mt-1 flex justify-between gap-4 text-[11px] text-slate-600">
                    <span>{formatBytes(job.bytesDownloaded)}{job.totalBytes ? ` / ${formatBytes(job.totalBytes)}` : ""}</span>
                    <span className="truncate">{job.error ?? job.repoId}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      <section className="border border-white/10 bg-[#0a1119] p-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-white">Installed models</h2>
            <p className="mt-1 text-xs text-slate-500">{primaryModels.length} primary models, {models.length - primaryModels.length} attached artifacts</p>
          </div>
          <CheckCircle2 className="h-5 w-5 text-emerald-300" />
        </div>
        <div className="mt-3 space-y-2">
          {primaryModels.map((model) => {
            const companions = companionMap.get(model.path) ?? [];
            const open = expanded.has(model.path);
            const settingsOpen = settingsPath === model.path;
            return (
              <div key={model.path} className="border border-white/10 bg-[#070c12]">
                <div className="grid gap-3 p-3 md:grid-cols-[auto_1fr_auto_auto] md:items-center">
                  <button title={open ? "Hide attached files" : "Show attached files"} onClick={() => setExpanded((current) => { const next = new Set(current); if (open) next.delete(model.path); else next.add(model.path); return next; })} className="p-1 text-slate-500">
                    {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                  </button>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-medium text-white">{model.name}</span>
                      {model.active ? <span className="border border-emerald-400/30 px-1.5 py-0.5 text-[10px] uppercase text-emerald-300">active</span> : null}
                      {model.served ? <span className="border border-cyan-400/30 px-1.5 py-0.5 text-[10px] uppercase text-cyan-300">served</span> : null}
                      {model.defaultModel ? <span className="border border-amber-400/30 px-1.5 py-0.5 text-[10px] uppercase text-amber-300">default</span> : null}
                    </div>
                    <div className="truncate font-mono text-[11px] text-slate-600">{model.servedAlias ?? model.path}</div>
                    <div className="mt-0.5 text-[10px] text-slate-700">{companions.length} attached artifact{companions.length === 1 ? "" : "s"} · {settingsSummary(model)}</div>
                  </div>
                  <div className="text-right text-xs text-slate-400">{formatBytes(model.sizeBytes + companions.reduce((sum, item) => sum + item.sizeBytes, 0))}</div>
                  <div className="flex items-center gap-1">
                    <button title={model.served ? "Hide from models endpoint" : "Expose on models endpoint"} onClick={() => void updateServing(model, { served: !model.served })} className="p-2 text-cyan-300 hover:bg-cyan-400/10">{model.served ? <Eye className="h-4 w-4" /> : <EyeOff className="h-4 w-4" />}</button>
                    <button disabled={model.defaultModel} title="Use as fallback model" onClick={() => void updateServing(model, { defaultModel: true, served: true })} className="p-2 text-amber-300 hover:bg-amber-400/10 disabled:opacity-30"><Star className="h-4 w-4" /></button>
                    <button title={settingsOpen ? "Close model settings" : "Edit model settings"} onClick={() => openSettings(model)} className="p-2 text-violet-300 hover:bg-violet-400/10">{settingsOpen ? <X className="h-4 w-4" /> : <SlidersHorizontal className="h-4 w-4" />}</button>
                    <button disabled={model.active || activatingPath !== null} title="Load model and attached files" onClick={() => void activate(model)} className="p-2 text-emerald-300 hover:bg-emerald-400/10 disabled:opacity-30">{activatingPath === model.path ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Power className="h-4 w-4" />}</button>
                    <button disabled={model.active} title="Delete model bundle" onClick={() => void remove(model)} className="p-2 text-rose-300 hover:bg-rose-400/10 disabled:opacity-30"><Trash2 className="h-4 w-4" /></button>
                  </div>
                </div>
                {settingsOpen ? <ModelSettingsPanel model={model} form={settingsForms[model.path] ?? defaultSettings(model)} saving={savingSettingsPath === model.path} onChange={(values) => updateSettings(model.path, values)} onSave={() => void saveSettings(model)} /> : null}
                {open ? companions.map((companion) => <CompanionRow key={companion.path} model={companion} />) : null}
              </div>
            );
          })}
          {unattached.length ? (
            <div className="border border-amber-400/20 bg-amber-400/5">
              <div className="px-3 py-2 text-xs font-medium text-amber-200">Unattached companion files</div>
              {unattached.map((model) => <CompanionRow key={model.path} model={model} />)}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function ModelSettingsPanel({
  model,
  form,
  saving,
  onChange,
  onSave,
}: {
  model: ModelAsset;
  form: ModelSettingsForm;
  saving: boolean;
  onChange: (values: Partial<ModelSettingsForm>) => void;
  onSave: () => void;
}) {
  const companionText = [model.draftPath ? "MTP" : null, model.projectorPath ? "mmproj" : null].filter(Boolean).join(" + ") || "none";
  return (
    <div className="border-t border-white/10 bg-[#05090e] p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs font-medium text-slate-200">Launch settings</div>
          <div className="mt-0.5 text-[11px] text-slate-600">Attached: {companionText}</div>
        </div>
        <button disabled={saving} onClick={onSave} className="inline-flex items-center gap-2 border border-emerald-400/30 bg-emerald-400/10 px-3 py-1.5 text-xs text-emerald-200 disabled:opacity-50">
          {saving ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          Save settings
        </button>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <NumberField label="Context" value={form.ctxSize} min={1024} max={262144} step={1024} onChange={(ctxSize) => onChange({ ctxSize })} />
        <TextField label="GPU layers" value={form.gpuLayers} onChange={(gpuLayers) => onChange({ gpuLayers })} />
        <NumberField label="Batch" value={form.batchSize} min={64} max={8192} step={64} onChange={(batchSize) => onChange({ batchSize })} />
        <NumberField label="Microbatch" value={form.uBatchSize} min={32} max={4096} step={32} onChange={(uBatchSize) => onChange({ uBatchSize })} />
        <NumberField label="Cache RAM MiB" value={form.cacheRamMiB} min={0} max={131072} step={512} onChange={(cacheRamMiB) => onChange({ cacheRamMiB })} />
        <SelectField label="K cache" value={form.cacheTypeK} options={["q4_0", "q5_0", "q8_0", "f16"]} onChange={(cacheTypeK) => onChange({ cacheTypeK })} />
        <SelectField label="V cache" value={form.cacheTypeV} options={["q4_0", "q5_0", "q8_0", "f16"]} onChange={(cacheTypeV) => onChange({ cacheTypeV })} />
        <NumberField label="Cache reuse" value={form.cacheReuse} min={0} max={262144} step={128} onChange={(cacheReuse) => onChange({ cacheReuse })} />
        <SelectField label="Spec decode" value={form.specType} options={["draft-mtp", "none"]} onChange={(specType) => onChange({ specType: specType as ModelSettingsForm["specType"] })} />
        <NumberField label="Draft tokens" value={form.specDraftNMax} min={1} max={16} step={1} onChange={(specDraftNMax) => onChange({ specDraftNMax })} />
        <SelectField label="Flash attention" value={form.flashAttention} options={["on", "auto", "off"]} onChange={(flashAttention) => onChange({ flashAttention: flashAttention as ModelSettingsForm["flashAttention"] })} />
        <NumberField label="Image min tokens" value={form.imageMinTokens} min={0} max={8192} step={128} onChange={(imageMinTokens) => onChange({ imageMinTokens })} />
      </div>
      <div className="mt-3 flex flex-wrap gap-4">
        <label className="inline-flex items-center gap-2 text-xs text-slate-300">
          <input type="checkbox" checked={form.metrics} onChange={(event) => onChange({ metrics: event.target.checked })} className="h-4 w-4 accent-cyan-400" />
          Metrics
        </label>
        <label className="inline-flex items-center gap-2 text-xs text-slate-300">
          <input type="checkbox" checked={form.jinja} onChange={(event) => onChange({ jinja: event.target.checked })} className="h-4 w-4 accent-cyan-400" />
          Jinja
        </label>
      </div>
    </div>
  );
}

function NumberField({ label, value, min, max, step, onChange }: { label: string; value: number; min: number; max: number; step: number; onChange: (value: number) => void }) {
  return (
    <label className="block">
      <span className="text-[11px] text-slate-500">{label}</span>
      <input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} className="mt-1 w-full border border-white/10 bg-[#070c12] px-2 py-2 text-xs text-slate-200 outline-none focus:border-cyan-400/50" />
    </label>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="text-[11px] text-slate-500">{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full border border-white/10 bg-[#070c12] px-2 py-2 text-xs text-slate-200 outline-none focus:border-cyan-400/50" />
    </label>
  );
}

function SelectField({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="text-[11px] text-slate-500">{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full border border-white/10 bg-[#070c12] px-2 py-2 text-xs text-slate-200 outline-none focus:border-cyan-400/50">
        {options.map((option) => <option key={option}>{option}</option>)}
      </select>
    </label>
  );
}
