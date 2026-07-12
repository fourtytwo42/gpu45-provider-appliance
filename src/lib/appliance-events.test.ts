import { describe, expect, it, vi } from "vitest";

describe("appliance event client", () => {
  it("exposes a single default event stream module", async () => {
    const constructor = vi.fn();
    vi.stubGlobal("EventSource", constructor);
    const eventClient = await import("./appliance-events");
    expect(eventClient.subscribeApplianceEvent).toBeTypeOf("function");
    expect(eventClient.subscribeApplianceConnection).toBeTypeOf("function");
    vi.unstubAllGlobals();
  });
});
