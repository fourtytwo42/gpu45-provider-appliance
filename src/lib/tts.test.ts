import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.restoreAllMocks();
  vi.resetModules();
});

describe("tts client", () => {
  it("collects a healthy TTS snapshot", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/snapshot?view=summary")) return Response.json({
        voices: [{ id: "voice-1", name: "Narrator", instruct: "Warm", language: "English", created_at: "now" }],
        voiceJobs: [],
        models: [{ id: "model-1", name: "Narrator clone", voice_id: "voice-1", status: "ready", created_at: "now" }],
        synthesisJobs: [],
        audiobookJobs: [],
        presentationJobs: [],
      });
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

  it("builds synthesis playback and download URLs for the tracked API route", async () => {
    const { ttsSynthesisAudioUrl } = await import("./tts");

    expect(ttsSynthesisAudioUrl("job id")).toBe("/api/tts/audio?id=job+id");
    expect(ttsSynthesisAudioUrl("job id", true)).toBe("/api/tts/audio?id=job+id&download=1");
  });
});
