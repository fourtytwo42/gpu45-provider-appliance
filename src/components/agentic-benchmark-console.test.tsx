import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgenticBenchmarkConsole } from "./agentic-benchmark-console";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("AgenticBenchmarkConsole", () => {
  it("clears a recovered coordinator error after a successful refresh", async () => {
    let coordinatorAvailable = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/models")) {
        return coordinatorAvailable
          ? { ok: true, json: async () => ({ models: [] }) }
          : { ok: false, json: async () => ({ error: "unable to open database file" }) };
      }
      if (url.endsWith("/suites")) return { ok: true, json: async () => ({ suites: [] }) };
      return { ok: true, json: async () => ({ campaigns: [] }) };
    }));

    render(<AgenticBenchmarkConsole initialModels={[]} initialSuites={[]} initialCampaigns={[]} />);

    fireEvent.click(screen.getByTitle("Refresh model qualifications"));
    expect(await screen.findByText("unable to open database file")).toBeInTheDocument();

    coordinatorAvailable = true;
    fireEvent.click(screen.getByTitle("Refresh model qualifications"));

    await waitFor(() => expect(screen.queryByText("unable to open database file")).not.toBeInTheDocument());
  });
});
