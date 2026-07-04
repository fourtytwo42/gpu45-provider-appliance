import type { FanChannel, FanCurveProfile } from "./types";

export type FanCurvePreset = Omit<FanCurveProfile, "channels" | "idlePwm" | "startupPwm" | "startupSeconds"> & {
  id: string;
  summary: string;
  testResult: string;
  idlePwm: number;
  startupPwm: number;
  startupSeconds: number;
  channels: FanChannel[];
};

const sharedProfile = {
  fanStopBelowC: null,
  fanStartAtC: null,
  idlePwm: 70,
  startupPwm: 255,
  startupSeconds: 6,
  channels: [
    { pwm: "pwm3", fan: "fan3_input", label: "gpu-fan-a" },
    { pwm: "pwm4", fan: "fan4_input", label: "gpu-fan-b" },
  ],
  active: false,
};

export const fanCurvePresets = [
  {
    id: "quiet-guard",
    name: "Quiet Guard",
    description: "Best tested balance. Quiet idle, delayed ramp, full fan before junction can pass 90C.",
    summary: "Recommended",
    testResult: "Gemma4 31B 10-minute soak: 86C max junction, 85C p95, no thermal abort.",
    ...sharedProfile,
    points: [
      { temperatureC: 35, pwm: 70 },
      { temperatureC: 50, pwm: 75 },
      { temperatureC: 60, pwm: 95 },
      { temperatureC: 70, pwm: 140 },
      { temperatureC: 78, pwm: 190 },
      { temperatureC: 84, pwm: 255 },
      { temperatureC: 100, pwm: 255 },
    ],
  },
  {
    id: "balanced-guard",
    name: "Balanced Guard",
    description: "Slightly earlier full-fan guard than the late curve, but it did not beat Quiet Guard in testing.",
    summary: "Conservative",
    testResult: "Gemma4 31B 10-minute soak: 87C max junction, 86C p95.",
    ...sharedProfile,
    points: [
      { temperatureC: 35, pwm: 70 },
      { temperatureC: 55, pwm: 70 },
      { temperatureC: 65, pwm: 95 },
      { temperatureC: 75, pwm: 145 },
      { temperatureC: 80, pwm: 195 },
      { temperatureC: 85, pwm: 255 },
      { temperatureC: 100, pwm: 255 },
    ],
  },
  {
    id: "aggressive-cool",
    name: "Aggressive Cool",
    description: "Original safer curve. It ramps sooner and is louder under load, but holds temperature tightly.",
    summary: "Coolest",
    testResult: "Gemma4 load: about 85C max junction, but full fan by 75C.",
    ...sharedProfile,
    points: [
      { temperatureC: 35, pwm: 70 },
      { temperatureC: 40, pwm: 80 },
      { temperatureC: 45, pwm: 100 },
      { temperatureC: 55, pwm: 150 },
      { temperatureC: 65, pwm: 210 },
      { temperatureC: 75, pwm: 255 },
      { temperatureC: 100, pwm: 255 },
    ],
  },
  {
    id: "late-guard",
    name: "Late Guard",
    description: "Quietest tested sustained-load curve, but it leaves very little margin under the 90C ceiling.",
    summary: "Experimental",
    testResult: "Gemma4 31B 10-minute soak: 89C max junction. Use only when you accept narrow margin.",
    ...sharedProfile,
    points: [
      { temperatureC: 35, pwm: 70 },
      { temperatureC: 55, pwm: 70 },
      { temperatureC: 65, pwm: 95 },
      { temperatureC: 75, pwm: 140 },
      { temperatureC: 82, pwm: 210 },
      { temperatureC: 86, pwm: 255 },
      { temperatureC: 100, pwm: 255 },
    ],
  },
] satisfies FanCurvePreset[];

export function getFanCurvePreset(id: string): FanCurvePreset | undefined {
  return fanCurvePresets.find((preset) => preset.id === id);
}

export function toFanCurveProfile(preset: FanCurvePreset): FanCurveProfile {
  return {
    name: preset.name,
    description: preset.description,
    fanStopBelowC: preset.fanStopBelowC,
    fanStartAtC: preset.fanStartAtC,
    idlePwm: preset.idlePwm,
    startupPwm: preset.startupPwm,
    startupSeconds: preset.startupSeconds,
    channels: preset.channels.map((channel) => ({ ...channel })),
    points: preset.points.map((point) => ({ ...point })),
    active: true,
  };
}

export function isSameFanCurve(a: FanCurveProfile | undefined, b: FanCurveProfile): boolean {
  if (!a) return false;
  if (a.name === b.name) return true;
  if (a.points.length !== b.points.length) return false;
  return a.points.every((point, index) => {
    const other = b.points[index];
    return other.temperatureC === point.temperatureC && other.pwm === point.pwm;
  });
}
