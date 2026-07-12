import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ touchResourceWorker: vi.fn() }));

vi.mock("./config", () => ({ isLiveRuntime: () => true }));
vi.mock("./resource-manager", () => ({ touchResourceWorker: mocks.touchResourceWorker }));

import { managedServiceFetch } from "./managed-service";

describe("managedServiceFetch", () => {
  beforeEach(() => {
    mocks.touchResourceWorker.mockReset();
    vi.unstubAllGlobals();
  });

  it("does not wake a worker for a read-only snapshot", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await managedServiceFetch("image", "http://127.0.0.1/health");
    expect(mocks.touchResourceWorker).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("touches a worker before a requested operation", async () => {
    mocks.touchResourceWorker.mockResolvedValue({});
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await managedServiceFetch("tts", "http://127.0.0.1/synthesize", { method: "POST" }, { wake: true });
    expect(mocks.touchResourceWorker).toHaveBeenCalledWith("tts");
    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
