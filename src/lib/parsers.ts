import type { FanPoint } from "./types";

export function parsePrometheusMetric(text: string, metricName: string): number | null {
  const regex = new RegExp(`^${metricName}(?:\\{[^}]*\\})?\\s+([\\d.]+)`, "m");
  const match = text.match(regex);
  return match ? Number(match[1]) : null;
}

export function parsePrometheusSample(text: string, metricNames: string[]): Record<string, number> {
  const result: Record<string, number> = {};
  for (const name of metricNames) {
    const value = parsePrometheusMetric(text, name);
    if (value !== null) {
      result[name] = value;
    }
  }
  return result;
}

function normalizeKey(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").replace(/\s+/g, " ").trim();
}

function toNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const parsed = Number(value.replaceAll(",", "").trim());
  return Number.isFinite(parsed) ? parsed : null;
}

function flattenEntries(value: unknown, entries: Array<{ key: string; value: unknown }> = []): Array<{ key: string; value: unknown }> {
  if (Array.isArray(value)) {
    for (const item of value) {
      flattenEntries(item, entries);
    }
    return entries;
  }

  if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value as Record<string, unknown>)) {
      entries.push({ key, value: child });
      flattenEntries(child, entries);
    }
  }

  return entries;
}

function findNumericValue(root: unknown, keyHints: string[]): number | null {
  const entries = flattenEntries(root);
  const normalizedHints = keyHints.map(normalizeKey);
  for (const entry of entries) {
    const normalizedKey = normalizeKey(entry.key);
    if (!normalizedHints.some((hint) => normalizedKey.includes(hint))) continue;
    const numeric = toNumber(entry.value);
    if (numeric !== null) return numeric;
  }
  return null;
}

export function parseRocmSmiJson(text: string): {
  gpuTempEdgeC: number | null;
  gpuTempJunctionC: number | null;
  gpuTempMemoryC: number | null;
  gpuUsage: number | null;
  vramTotalBytes: number | null;
  vramUsedBytes: number | null;
} {
  try {
    const json = JSON.parse(text) as unknown;
    return {
      gpuTempEdgeC: findNumericValue(json, ["temperature sensor edge", "temperature edge", "edge temperature"]),
      gpuTempJunctionC: findNumericValue(json, ["temperature sensor junction", "temperature junction", "junction temperature"]),
      gpuTempMemoryC: findNumericValue(json, ["temperature sensor memory", "temperature memory", "memory temperature"]),
      gpuUsage: findNumericValue(json, ["gpu use", "gpu usage"]),
      vramTotalBytes: findNumericValue(json, ["vram total memory", "vram total"]),
      vramUsedBytes: findNumericValue(json, ["vram total used memory", "vram used memory", "vram used"]),
    };
  } catch {
    return {
      gpuTempEdgeC: null,
      gpuTempJunctionC: null,
      gpuTempMemoryC: null,
      gpuUsage: null,
      vramTotalBytes: null,
      vramUsedBytes: null,
    };
  }
}

export function parseCurvePoints(text: string): FanPoint[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [temperatureC, pwm] = line.split(",").map((part) => Number(part.trim()));
      return { temperatureC, pwm };
    })
    .filter((point) => Number.isFinite(point.temperatureC) && Number.isFinite(point.pwm));
}

export function serializeCurvePoints(points: FanPoint[]): string {
  return points.map((point) => `${point.temperatureC},${point.pwm}`).join("\n") + "\n";
}
