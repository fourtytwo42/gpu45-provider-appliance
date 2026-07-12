"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { MetricSeries } from "@/lib/types";

export function OperationalChart({ title, subtitle, series }: { title: string; subtitle: string; series: MetricSeries[] }) {
  const rows = new Map<string, Record<string, string | number>>();
  for (const item of series) {
    for (const point of item.points) {
      const row = rows.get(point.timestamp) ?? { timestamp: point.timestamp };
      row[item.kind] = point.value;
      rows.set(point.timestamp, row);
    }
  }
  const data = [...rows.values()].sort((a, b) => String(a.timestamp).localeCompare(String(b.timestamp))).slice(-180);
  return (
    <section className="min-h-72 border border-white/10 bg-[#0a1119] p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="text-sm font-semibold text-white">{title}</h2><p className="mt-1 text-xs text-slate-500">{subtitle}</p></div>
        <div className="flex flex-wrap gap-3">
          {series.map((item) => <span key={item.kind} className="flex items-center gap-1.5 text-xs text-slate-400"><span className="h-2 w-2" style={{ background: item.color }} />{item.label}</span>)}
        </div>
      </div>
      {data.length < 2 ? <div className="flex h-56 items-center justify-center border border-dashed border-white/10 text-sm text-slate-500">Collecting samples...</div> : (
        <ResponsiveContainer width="100%" height={230}>
          <LineChart data={data} margin={{ left: -12, right: 8, top: 8, bottom: 0 }}>
            <CartesianGrid stroke="rgba(148,163,184,.12)" vertical={false} />
            <XAxis dataKey="timestamp" tickFormatter={(value) => new Date(value).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", timeZone: "America/Chicago" })} stroke="#526173" tick={{ fontSize: 10 }} minTickGap={36} />
            <YAxis stroke="#526173" tick={{ fontSize: 10 }} width={48} />
            <Tooltip contentStyle={{ background: "#070b10", border: "1px solid #263241", borderRadius: 4 }} labelFormatter={(value) => new Date(String(value)).toLocaleString("en-US", { timeZone: "America/Chicago" })} />
            {series.map((item) => <Line key={item.kind} type="monotone" dataKey={item.kind} name={`${item.label} (${item.unit})`} stroke={item.color} strokeWidth={2} dot={false} connectNulls />)}
          </LineChart>
        </ResponsiveContainer>
      )}
    </section>
  );
}
