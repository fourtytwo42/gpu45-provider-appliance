import { cn } from "@/lib/cn";
import type { MetricSeries } from "@/lib/types";

function buildSparkline(series?: MetricSeries): { linePath: string; areaPath: string; hasData: boolean } {
  const points = series?.points ?? [];
  if (points.length === 0) {
    return { linePath: "", areaPath: "", hasData: false };
  }

  const width = 120;
  const height = 44;
  const padding = 4;
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = points.length > 1 ? (width - padding * 2) / (points.length - 1) : 0;
  const coords = points.map((point, index) => {
    const x = padding + step * index;
    const y = height - padding - ((point.value - min) / range) * (height - padding * 2);
    return [x, y] as const;
  });
  const linePath = coords.length > 0 ? `M ${coords.map(([x, y]) => `${x.toFixed(2)} ${y.toFixed(2)}`).join(" L ")}` : "";
  const tail = coords[coords.length - 1];
  const areaPath =
    coords.length > 0
      ? `${linePath} L ${(tail?.[0] ?? width - padding).toFixed(2)} ${(height - padding).toFixed(2)} L ${padding.toFixed(2)} ${(height - padding).toFixed(2)} Z`
      : "";
  return { linePath, areaPath, hasData: coords.length > 0 };
}

export function MetricCard({
  label,
  value,
  subvalue,
  trend,
  accent = "cyan",
}: {
  label: string;
  value: string;
  subvalue?: string;
  trend?: MetricSeries;
  accent?: "cyan" | "sky" | "amber" | "emerald" | "rose" | "violet";
}) {
  const accentStyles: Record<string, string> = {
    cyan: "from-cyan-400/20 to-cyan-400/5 border-cyan-400/20",
    sky: "from-sky-400/20 to-sky-400/5 border-sky-400/20",
    amber: "from-amber-400/20 to-amber-400/5 border-amber-400/20",
    emerald: "from-emerald-400/20 to-emerald-400/5 border-emerald-400/20",
    rose: "from-rose-400/20 to-rose-400/5 border-rose-400/20",
    violet: "from-violet-400/20 to-violet-400/5 border-violet-400/20",
  };
  const sparkline = buildSparkline(trend);
  const chartColor = trend?.color ?? "#67e8f9";

  return (
    <div className={cn("rounded-lg border bg-gradient-to-b p-4 shadow-lg shadow-black/20", accentStyles[accent])}>
      <div className="text-[11px] uppercase tracking-[0.18em] text-slate-400">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-white">{value}</div>
      {subvalue ? <div className="mt-1 text-sm text-slate-400">{subvalue}</div> : null}
      {sparkline.hasData ? (
        <svg viewBox="0 0 120 44" className="mt-3 h-11 w-full" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id={`spark-${label.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={chartColor} stopOpacity="0.28" />
              <stop offset="100%" stopColor={chartColor} stopOpacity="0.02" />
            </linearGradient>
          </defs>
          <path d={sparkline.areaPath} fill={`url(#spark-${label.replace(/[^a-z0-9]+/gi, "-").toLowerCase()})`} />
          <path d={sparkline.linePath} fill="none" stroke={chartColor} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : null}
    </div>
  );
}
