import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.restoreAllMocks();
  vi.resetModules();
});

describe("tts client", () => {
  it("collects a healthy TTS snapshot", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/health")) return Response.json({ status: "ok" });
      if (url.endsWith("/voices")) return Response.json([{ id: "voice-1", name: "Narrator", instruct: "Warm", language: "English", created_at: "now" }]);
      if (url.endsWith("/models")) return Response.json([{ id: "model-1", name: "Narrator clone", voice_id: "voice-1", status: "ready", created_at: "now" }]);
      return new Response("not found", { status: 404 });
    }));

    const { getTtsSnapshot } = await import("./tts");
    const snapshot = await getTtsSnapshot();

    expect(snapshot.healthy).toBe(true);
    expect(snapshot.voices).toHaveLength(1);
    expect(snapshot.models[0].status).toBe("ready");
  });

  it("reports offline when health fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("down", { status: 503 })));

    const { getTtsSnapshot } = await import("./tts");
    const snapshot = await getTtsSnapshot();

    expect(snapshot.healthy).toBe(false);
    expect(snapshot.voices).toEqual([]);
    expect(snapshot.error).toContain("down");
  });
});
