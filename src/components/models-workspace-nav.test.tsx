import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelsWorkspaceNav } from "./models-workspace-nav";

const { usePathname } = vi.hoisted(() => ({ usePathname: vi.fn() }));

vi.mock("next/navigation", () => ({ usePathname }));

describe("ModelsWorkspaceNav", () => {
  beforeEach(() => usePathname.mockReturnValue("/models"));

  it("exposes every models workspace destination from the library", () => {
    render(<ModelsWorkspaceNav />);
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute("href", "/models");
    expect(screen.getByRole("link", { name: "Benchmarks" })).toHaveAttribute("href", "/benchmarks");
    expect(screen.getByRole("link", { name: "API Access" })).toHaveAttribute("href", "/keys");
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute("aria-current", "page");
  });
});
