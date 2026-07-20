import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { WhisperSnapshot } from "@/lib/whisper";
import { WhisperConsole } from "./whisper-console";

vi.mock("@/lib/appliance-events", () => ({
  subscribeApplianceEvent: () => () => undefined,
}));

const snapshot = {
  healthy: true,
  serviceUrl: "http://127.0.0.1:8020",
  models: ["small"],
  outlineModel: "ornith-fast",
  jobs: [{
    id: "transcript-1",
    filename: "meeting.mp4",
    model: "small",
    task: "transcribe",
    status: "completed",
    created_at: "2026-07-20T00:00:00Z",
    transcript_path: "/models/whisper/transcripts/meeting.md",
    outline_status: "completed",
    outline_path: "/models/whisper/outlines/meeting-outline.md",
    outline_model: "ornith-fast",
  }],
} satisfies WhisperSnapshot;

describe("WhisperConsole", () => {
  it("offers automatic outlines and separate Markdown downloads", () => {
    render(<WhisperConsole initialSnapshot={snapshot} />);

    expect(screen.getByRole("checkbox", { name: /Generate outline after transcription/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Transcript/i })).toHaveAttribute("href", "/api/whisper/output?id=transcript-1");
    expect(screen.getByRole("link", { name: /Outline/i })).toHaveAttribute("href", "/api/whisper/output?id=transcript-1&asset=outline");
    expect(screen.getByRole("button", { name: /Refresh outline/i })).toBeEnabled();
    expect(screen.getByText(/ornith-fast/)).toBeInTheDocument();
  });
});
