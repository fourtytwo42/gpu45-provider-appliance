import { Fan, ShieldCheck, Thermometer, Zap } from "lucide-react";
import { collectDashboardSnapshot } from "@/lib/collectors";
import { fanCurvePresets, isSameFanCurve, toFanCurveProfile } from "@/lib/fan-presets";
import { SectionCard } from "@/components/section-card";
import { applyFanCurvePresetAction } from "../actions";

export const dynamic = "force-dynamic";

function formatCurve(points: Array<{ temperatureC: number; pwm: number }>): string {
  return points.map((point) => `${point.temperatureC}C/${point.pwm}`).join(" -> ");
}

export default async function SettingsPage() {
  const snapshot = await collectDashboardSnapshot();
  const activeCurve = snapshot.fanCurves.find((curve) => curve.active) ?? snapshot.fanCurves[0];
  const fanPwm = snapshot.system.fanPwm === null ? "n/a" : Math.round(snapshot.system.fanPwm);
  const fanRpm = snapshot.system.fanRpm === null ? "n/a" : `${Math.round(snapshot.system.fanRpm).toLocaleString()} RPM`;
  const junction = snapshot.system.gpuTempJunctionC === null ? "n/a" : `${Math.round(snapshot.system.gpuTempJunctionC)}C`;

  return (
    <div className="grid gap-4 xl:grid-cols-[1.45fr_0.85fr]">
      <SectionCard title="Fan curve presets" description="Apply a tested GPU fan curve with guardrails">
        <div className="grid gap-3 lg:grid-cols-2">
          {fanCurvePresets.map((preset) => {
            const profile = toFanCurveProfile(preset);
            const active = isSameFanCurve(activeCurve, profile);
            return (
              <form
                key={preset.id}
                action={applyFanCurvePresetAction}
                className={`rounded-lg border p-4 transition ${
                  active
                    ? "border-cyan-300/60 bg-cyan-400/10 shadow-lg shadow-cyan-950/30"
                    : "border-white/10 bg-slate-950/60 hover:border-cyan-300/30"
                }`}
              >
                <input type="hidden" name="presetId" value={preset.id} />
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <Fan className={active ? "h-4 w-4 text-cyan-200" : "h-4 w-4 text-slate-400"} />
                      <h3 className="text-sm font-semibold text-white">{preset.name}</h3>
                    </div>
                    <div className="mt-1 text-xs font-medium uppercase tracking-[0.16em] text-cyan-200">{preset.summary}</div>
                  </div>
                  {active ? (
                    <span className="rounded-md border border-cyan-300/40 bg-cyan-300/10 px-2 py-1 text-[11px] font-medium text-cyan-100">
                      Active
                    </span>
                  ) : null}
                </div>

                <p className="mt-3 text-sm leading-6 text-slate-300">{preset.description}</p>
                <div className="mt-3 rounded-md border border-white/10 bg-black/20 p-3">
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <Thermometer className="h-3.5 w-3.5 text-rose-300" />
                    Tested result
                  </div>
                  <p className="mt-1 text-xs leading-5 text-slate-300">{preset.testResult}</p>
                </div>
                <div className="mt-3 font-mono text-[11px] leading-5 text-slate-500">{formatCurve(preset.points)}</div>
                <button
                  disabled={active}
                  className={`mt-4 w-full rounded-md border px-3 py-2 text-sm font-medium ${
                    active
                      ? "cursor-not-allowed border-white/10 bg-white/5 text-slate-500"
                      : "border-cyan-300/30 bg-cyan-300/10 text-cyan-100 hover:bg-cyan-300/20"
                  }`}
                >
                  {active ? "Applied" : "Apply preset"}
                </button>
              </form>
            );
          })}
        </div>
      </SectionCard>

      <div className="space-y-4">
        <SectionCard title="Current cooling state" description="Live fan controller values">
          <div className="grid gap-3">
            <div className="rounded-lg border border-white/10 bg-slate-950/60 p-3">
              <div className="flex items-center gap-2 text-xs uppercase tracking-[0.16em] text-slate-500">
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-300" />
                Active curve
              </div>
              <div className="mt-2 text-sm font-semibold text-white">{activeCurve?.name ?? "unknown"}</div>
              <div className="mt-1 text-xs leading-5 text-slate-400">{activeCurve?.description ?? "No description available."}</div>
            </div>
            <div className="grid grid-cols-3 gap-3 text-center">
              <div className="rounded-lg border border-white/10 bg-slate-950/60 p-3">
                <Thermometer className="mx-auto h-4 w-4 text-rose-300" />
                <div className="mt-2 font-mono text-sm text-white">{junction}</div>
                <div className="text-[11px] text-slate-500">junction</div>
              </div>
              <div className="rounded-lg border border-white/10 bg-slate-950/60 p-3">
                <Zap className="mx-auto h-4 w-4 text-amber-300" />
                <div className="mt-2 font-mono text-sm text-white">{fanPwm}</div>
                <div className="text-[11px] text-slate-500">PWM</div>
              </div>
              <div className="rounded-lg border border-white/10 bg-slate-950/60 p-3">
                <Fan className="mx-auto h-4 w-4 text-cyan-300" />
                <div className="mt-2 font-mono text-sm text-white">{fanRpm}</div>
                <div className="text-[11px] text-slate-500">fan RPM</div>
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="Safety rules" description="Preset apply guardrails">
          <div className="space-y-2 text-sm leading-6 text-slate-300">
            <p>Minimum commanded fan speed is `70 PWM`, the measured reliable spin floor.</p>
            <p>Every preset must command `255 PWM` at or below `86C` to keep margin under the `90C` ceiling.</p>
            <p>The controller keeps the startup burst and both GPU fan headers mapped on every preset apply.</p>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

