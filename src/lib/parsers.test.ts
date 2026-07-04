import { describe, expect, it } from "vitest";
import { parseCurvePoints, parsePrometheusMetric, parseRocmSmiJson, serializeCurvePoints } from "./parsers";

describe("parsers", () => {
  it("parses prometheus metrics", () => {
    const text = `
llamacpp:requests_processing 2
llamacpp:tokens_predicted_total 42
`;
    expect(parsePrometheusMetric(text, "llamacpp:requests_processing")).toBe(2);
    expect(parsePrometheusMetric(text, "llamacpp:tokens_predicted_total")).toBe(42);
  });

  it("parses rocm smi json", () => {
    const text = JSON.stringify({
      card0: {
        "Temperature (Sensor edge) (C)": "29.0",
        "Temperature (Sensor junction) (C)": "33.0",
        "Temperature (Sensor memory) (C)": "28.0",
        "GPU use (%)": "5",
        "VRAM Total Memory (B)": "10",
        "VRAM Total Used Memory (B)": "8",
      },
    });
    const parsed = parseRocmSmiJson(text);
    expect(parsed.gpuTempEdgeC).toBe(29);
    expect(parsed.gpuUsage).toBe(5);
  });

  it("parses nested rocm smi json with alternate labels", () => {
    const text = JSON.stringify({
      adapter: {
        metrics: {
          temperatures: {
            "Edge Temperature (C)": "31.5",
            "Junction Temperature (C)": "44.0",
            "Memory Temperature (C)": "29.25",
          },
          utilization: {
            "GPU Usage (%)": "12",
          },
          memory: {
            "VRAM Total Memory (B)": "32195477504",
            "VRAM Total Used Memory (B)": "29772996608",
          },
        },
      },
    });

    const parsed = parseRocmSmiJson(text);
    expect(parsed.gpuTempEdgeC).toBe(31.5);
    expect(parsed.gpuTempJunctionC).toBe(44);
    expect(parsed.gpuTempMemoryC).toBe(29.25);
    expect(parsed.gpuUsage).toBe(12);
    expect(parsed.vramTotalBytes).toBe(32195477504);
    expect(parsed.vramUsedBytes).toBe(29772996608);
  });

  it("round-trips fan curve points", () => {
    const curve = [
      { temperatureC: 35, pwm: 128 },
      { temperatureC: 45, pwm: 150 },
      { temperatureC: 55, pwm: 180 },
    ];
    expect(parseCurvePoints(serializeCurvePoints(curve))).toEqual(curve);
  });
});
