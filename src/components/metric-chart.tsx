"use client";

import {
  CartesianGrid,
  Area,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { cn } from "@/lib/cn";
import type { MetricSeries } from "@/lib/types";

function formatLatestValue(series: MetricSeries): string {
  const latest = series.points.at(-1)?.value;
  if (latest === undefined) return "n/a";
  if (series.unit === "%") return `${latest.toFixed(0)}%`;
  if (series.unit === "C") return `${latest.toFixed(1)} C`;
  if (series.unit === "W") return `${latest.toFixed(1)} W`;
  if (series.unit === "GB") return `${latest.toFixed(1)} GB`;
  if (series.unit === "rpm") return `${Math.round(latest)} rpm`;
  if (series.unit === "pwm") return `${Math.round(latest)}`;
  if (series.unit === "tok/s") return `${latest.toFixed(1)} tok/s`;
  return latest.toFixed(1);
}

export function MetricChart({
  series,
  className,
}: {
  series: MetricSeries;
  className?: string;
}) {
  const latestValue = formatLatestValue(series);

  return (
    <div className={cn("h-64 w-full rounded-lg border border-white/10 bg-slate-950/50 p-3", className)}>
      <div className="mb-2 flex items-end justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-white">{series.label}</div>
          <div className="text-xs text-slate-400">{series.unit || "value"}</div>
        </div>
        <div className="text-right">
          <div className="text-xl font-semibold text-white">{latestValue}</div>
          <div className="text-[11px] uppercase tracking-[0.14em] text-slate-500">latest</div>
        </div>
      </div>
      {series.points.length === 0 ? (
        <div className="flex h-[calc(100%-3rem)] items-center justify-center rounded-md border border-dashed border-white/10 text-sm text-slate-500">
          No samples yet
        </div>
      ) : (
        <ResponsiveContainer width="100%" height="85%">
          <LineChart data={series.points}>
            <CartesianGrid stroke="rgba(148,163,184,0.16)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="timestamp"
              tickFormatter={(value) => new Date(value).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: "America/Chicago" })}
              stroke="#64748b"
              tick={{ fontSize: 10 }}
            />
            <YAxis stroke="#64748b" tick={{ fontSize: 10 }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "#020617",
                border: "1px solid rgba(255,255,255,0.12)",
                borderRadius: "8px",
                color: "#f8fafc",
              }}
              labelFormatter={(value) => new Date(value as string).toLocaleString("en-US", { timeZone: "America/Chicago" })}
            />
            <Area type="monotone" dataKey="value" stroke="none" fill={series.color} fillOpacity={0.12} />
            <Line
              type="monotone"
              dataKey="value"
              stroke={series.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
