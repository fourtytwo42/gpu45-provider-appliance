import { describe, expect, it } from "vitest";
import { validatePublicHttpUrl } from "./research";

describe("research URL safety", () => {
  it("blocks localhost URLs", async () => {
    await expect(validatePublicHttpUrl("http://127.0.0.1:8888/search")).rejects.toThrow(/blocked|private|local/i);
  });

  it("allows normal public HTTPS URLs", async () => {
    const url = await validatePublicHttpUrl("https://example.com/path");
    expect(url.hostname).toBe("example.com");
  });
});
