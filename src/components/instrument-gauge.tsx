"use client";

import type { LucideIcon } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";

export function normalizeGaugeValue(value: number | null, max: number): number {
  if (value === null || !Number.isFinite(value) || max <= 0) return 0;
  return Math.max(0, Math.min(max, value));
}

export function InstrumentGauge({
  label,
  value,
  max,
  displayValue,
  detail,
  color,
  icon: Icon,
}: {
  label: string;
  value: number | null;
  max: number;
  displayValue: string;
  detail: string;
  color: string;
  icon: LucideIcon;
}) {
  const normalized = normalizeGaugeValue(value, max);
  const data = [
    { name: label, value: normalized },
    { name: "remaining", value: Math.max(0, max - normalized) },
  ];

  return (
    <article className="h-48 min-w-0 border border-white/10 bg-[#0a1119] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs uppercase text-slate-500">{label}</span>
        <Icon className="h-4 w-4 shrink-0" style={{ color }} aria-hidden="true" />
      </div>
      <div className="relative mt-1 h-28" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value ?? undefined}>
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              startAngle={180}
              endAngle={0}
              cx="50%"
              cy="82%"
              innerRadius="58%"
              outerRadius="76%"
              stroke="none"
              isAnimationActive={false}
            >
              <Cell fill={color} />
              <Cell fill="#1b2530" />
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-x-0 bottom-1 text-center">
          <div className="font-mono text-xl font-semibold text-white">{displayValue}</div>
        </div>
        <span className="absolute bottom-0 left-1 font-mono text-[10px] text-slate-600">0</span>
        <span className="absolute bottom-0 right-1 font-mono text-[10px] text-slate-600">{max.toLocaleString()}</span>
      </div>
      <div className="truncate text-center text-xs text-slate-500">{detail}</div>
    </article>
  );
}
