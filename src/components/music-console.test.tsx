import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MusicSnapshot } from "@/lib/music";
import { MusicConsole } from "./music-console";

vi.mock("@/lib/appliance-events", () => ({
  subscribeApplianceEvent: () => () => undefined,
}));

const snapshot = {
  healthy: true,
  profiles: [
    {
      id: "ace-xl-turbo-4b",
      name: "ACE-Step 1.5 XL Turbo + 4B LM",
      backend: "ace",
      model: "acestep-v15-xl-turbo",
      description: "Fast music generation.",
      recommended: true,
      experimental: false,
      noncommercial: false,
      modes: ["create", "reference", "edit", "stems"],
      taskTypes: ["text2music", "cover", "repaint", "extract"],
      duration: { min: 10, max: 600, default: 60 },
      stepOptions: [8],
      defaultSteps: 8,
      outputFormats: ["flac"],
      expectedVramGb: 24,
      ready: true,
      licenseAccepted: true,
    },
  ],
  jobs: [],
  license: { levo2: { hash: "license", text: "Noncommercial", accepted: true } },
} satisfies MusicSnapshot;

describe("MusicConsole", () => {
  it("keeps icon-only workflow controls accessible at narrow widths", () => {
    render(<MusicConsole initialSnapshot={snapshot} />);

    for (const name of ["Create", "Reference", "Edit", "Stems"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });
});
