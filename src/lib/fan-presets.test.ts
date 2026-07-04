import { describe, expect, it } from "vitest";
import { fanCurvePresets, getFanCurvePreset, isSameFanCurve, toFanCurveProfile } from "./fan-presets";

describe("fan curve presets", () => {
  it("includes the recommended quiet guard preset", () => {
    const preset = getFanCurvePreset("quiet-guard");

    expect(preset?.name).toBe("Quiet Guard");
    expect(preset?.points).toContainEqual({ temperatureC: 84, pwm: 255 });
  });

  it("keeps every preset inside the appliance safety envelope", () => {
    for (const preset of fanCurvePresets) {
      expect(preset.idlePwm).toBeGreaterThanOrEqual(70);
      expect(preset.startupPwm).toBe(255);
      expect(preset.channels).toEqual([
        { pwm: "pwm3", fan: "fan3_input", label: "gpu-fan-a" },
        { pwm: "pwm4", fan: "fan4_input", label: "gpu-fan-b" },
      ]);
      expect(preset.points.some((point) => point.temperatureC <= 86 && point.pwm === 255)).toBe(true);
      expect(preset.points.every((point) => point.pwm >= 70 && point.pwm <= 255)).toBe(true);
    }
  });

  it("creates an active full controller profile without mutating the preset", () => {
    const preset = getFanCurvePreset("quiet-guard");
    expect(preset).toBeDefined();

    const profile = toFanCurveProfile(preset!);
    profile.points[0].pwm = 71;

    expect(profile.active).toBe(true);
    expect(preset!.points[0].pwm).toBe(70);
  });

  it("matches current curves by points when names differ", () => {
    const preset = getFanCurvePreset("quiet-guard");
    const profile = toFanCurveProfile(preset!);

    expect(isSameFanCurve({ ...profile, name: "dual-gpu-fan-quiet-guard-88c" }, profile)).toBe(true);
  });
});

