import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { en, ko } from "./i18n";

describe("OpenTCAD static foundation", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("opentcad-locale", "en");
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("makes the static execution boundary explicit", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "Process workspace" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Static safety boundary")).toBeInTheDocument();
    expect(
      screen.getByText(
        /GitHub Pages cannot run SUPREM-IV\.GS, DEVSIM, shell commands, or containers/,
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Not solver output").length).toBeGreaterThan(0);
  });

  it("switches every maintained surface to Korean", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "한국어" }));

    expect(
      screen.getByRole("heading", { name: "공정 작업공간" }),
    ).toBeInTheDocument();
    expect(screen.getByText("정적 안전 경계")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("ko");
    expect(window.localStorage.getItem("opentcad-locale")).toBe("ko");
  });

  it("runs a deterministic reference-only workflow to completion", () => {
    vi.useFakeTimers();
    render(<App />);

    fireEvent.click(
      screen.getByRole("button", { name: "Run reference workflow" }),
    );
    expect(
      screen.getAllByText("Reference workflow running").length,
    ).toBeGreaterThan(0);

    for (let step = 0; step < 5; step += 1) {
      act(() => {
        vi.advanceTimersByTime(620);
      });
    }

    expect(
      screen.getAllByText("Reference workflow complete").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByRole("button", { name: "Run reference again" }),
    ).toBeEnabled();
  });

  it("explains the future runtime path without exposing an engine", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "Runtime" }));

    expect(
      screen.getByRole("heading", { name: "Runtime boundary" }),
    ).toBeInTheDocument();
    expect(screen.getByText("No network")).toBeInTheDocument();
    expect(screen.getByText("Fixed non-root user")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Read architecture/ })).toHaveAttribute(
      "href",
      expect.stringContaining("/docs/en/architecture.md"),
    );
  });

  it("keeps English and Korean translation keys in parity", () => {
    expect(Object.keys(ko).sort()).toEqual(Object.keys(en).sort());
  });

  it("keeps Korean UI copy free from em dash punctuation", () => {
    expect(Object.values(ko).filter((message) => message.includes("\u2014"))).toEqual([]);
  });
});
