import { describe, expect, it } from "vitest";
import { handleJsonRpc, summarizeJob } from "../../scripts/gpu45-mcp-server.mjs";

describe("GPU45 MCP music tools", () => {
  it("advertises the complete music tool set", async () => {
    const response = await handleJsonRpc({ jsonrpc: "2.0", id: 1, method: "tools/list" }) as { result: { tools: Array<{ name: string }> } };
    const names = response.result.tools.map((tool) => tool.name);
    expect(names).toEqual(expect.arrayContaining(["gpu45_music_generate", "gpu45_music_edit", "gpu45_music_get", "gpu45_music_cancel"]));
  });

  it("returns all completed music asset URLs", () => {
    const summary = summarizeJob("music", { id: "song one", status: "completed", assets: { master: "/master.wav", vocals: "/vocals.wav" } }, "http://gpu45") as unknown as { url: string; assets: Record<string, string> };
    expect(summary.url).toBe("http://gpu45/api/music/jobs/song%20one/output?asset=master");
    expect(summary.assets.vocals).toBe("http://gpu45/api/music/jobs/song%20one/output?asset=vocals");
  });
});
