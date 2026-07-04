import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.restoreAllMocks();
  vi.resetModules();
});

describe("video client", () => {
  it("collects a healthy video snapshot", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/health")) return Response.json({ status: "ok", model_ready: true });
      if (url.endsWith("/jobs")) return Response.json([{ id: "job-1", prompt: "test", size: "1280*704", steps: 20, duration_seconds: 5, frame_num: 121, seed: -1, status: "completed", created_at: "now" }]);
      return new Response("not found", { status: 404 });
    }));

    const { getVideoSnapshot } = await import("./video");
    const snapshot = await getVideoSnapshot();

    expect(snapshot.healthy).toBe(true);
    expect(snapshot.modelReady).toBe(true);
    expect(snapshot.jobs).toHaveLength(1);
  });

  it("forwards duration fields when creating a job", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toMatchObject({
        prompt: "test",
        duration_seconds: 15,
      });
      return Response.json({ id: "job-2", prompt: "test", size: "1280*704", steps: 20, duration_seconds: 15, frame_num: 361, seed: -1, status: "queued", created_at: "now" });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { createVideoJob } = await import("./video");
    const job = await createVideoJob({ prompt: "test", duration_seconds: 15 });

    expect(job.duration_seconds).toBe(15);
    expect(job.frame_num).toBe(361);
  });

  it("reports offline when the video service is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("down", { status: 503 })));

    const { getVideoSnapshot } = await import("./video");
    const snapshot = await getVideoSnapshot();

    expect(snapshot.healthy).toBe(false);
    expect(snapshot.modelReady).toBe(false);
    expect(snapshot.jobs).toEqual([]);
    expect(snapshot.error).toContain("down");
  });
});
