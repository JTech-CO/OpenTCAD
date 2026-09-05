import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { en, ko } from "./i18n";

describe("OpenTCAD static experience", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("opens on the English introduction and makes the release scope explicit", () => {
    render(<App />);

    expect(document.documentElement.lang).toBe("en");
    expect(document.querySelector(".landing-page")).toHaveAttribute(
      "data-ui",
      "precision-cad",
    );
    expect(
      screen.getByRole("link", { name: "Skip to main content" }),
    ).toHaveAttribute("href", "#landing-main");
    expect(screen.getByText("Understand the device.")).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Explore the workspace" }),
    ).toHaveLength(2);
    expect(
      screen.getByText(
        /GitHub Pages does not execute submitted decks, shell commands, containers/,
      ),
    ).toBeInTheDocument();
  }, 10_000);

  it("switches the introduction to Korean and persists the choice", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "한국어" }));

    expect(screen.getByText("소자를 이해합니다.")).toBeInTheDocument();
    expect(screen.getByText("브라우저 내부 솔버 실행 없음")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("ko");
    expect(window.localStorage.getItem("opentcad-locale")).toBe("ko");
  });

  it("enters the reference workspace and keeps its safety boundary explicit", () => {
    render(<App />);

    fireEvent.click(
      screen.getAllByRole("button", { name: "Explore the workspace" })[0],
    );

    expect(document.querySelector(".app-shell")).toHaveAttribute(
      "data-ui",
      "precision-cad",
    );
    expect(
      screen.getByRole("link", { name: "Skip to main content" }),
    ).toHaveAttribute("href", "#workspace-main");
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

  it("runs a deterministic reference-only workflow to completion", () => {
    vi.useFakeTimers();
    render(<App />);

    fireEvent.click(
      screen.getAllByRole("button", { name: "Explore the workspace" })[0],
    );
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

    await user.click(
      screen.getAllByRole("button", { name: "Explore the workspace" })[0],
    );
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
    expect(
      screen.getByRole("link", { name: /Review M3 entry gates/ }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining("/docs/en/m3-entry-gates.md"),
    );
    expect(
      screen.queryByRole("button", { name: "Connect local service" }),
    ).not.toBeInTheDocument();
  });

  it("connects only after an explicit local action and keeps execution blocked", async () => {
    const user = userEvent.setup();
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({
        schemaVersion: 1,
        serviceState: "ready",
        executionState: "blocked",
        manifestSha256: "a".repeat(64),
        backend: null,
        blockedGates: [
          "runtime-adapters",
          "native-fencing",
          "local-transport",
          "lifecycle-integration",
          "credentials-and-scheduler",
          "power-loss",
          "platform-qualification",
          "solver-release",
        ],
        recoveryState: "not-applicable",
        schedulerState: "not-started",
      }),
    } as unknown as Response);
    vi.stubGlobal("fetch", fetcher);
    render(<App localBootstrap={{ token: "A".repeat(43) }} />);

    await user.click(
      screen.getAllByRole("button", { name: "Explore the workspace" })[0],
    );
    await user.click(screen.getByRole("button", { name: "Runtime" }));
    expect(fetcher).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "Connect local service" }),
    );

    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(
      screen.getAllByText("Execution blocked by release gates").length,
    ).toBeGreaterThan(0);
    for (const label of [
      "Runtime adapters",
      "Native fencing",
      "Local transport",
      "Lifecycle integration",
      "Credentials and scheduler",
      "Power-loss recovery",
      "Platform qualification",
      "Solver release",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(
      within(screen.getByRole("list", { name: "Blocking gates" })).getAllByRole(
        "listitem",
      ),
    ).toHaveLength(8);
    expect(
      screen.queryByText(/runtime-adapters|solver-release/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Review M3 entry gates/ }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining("/docs/en/m3-entry-gates.md"),
    );

    await user.click(screen.getByRole("button", { name: "한국어" }));
    for (const label of [
      "런타임 어댑터",
      "네이티브 펜싱",
      "로컬 전송",
      "수명 주기 통합",
      "자격 증명 및 예약 실행",
      "전원 장애 복구",
      "플랫폼 자격 검증",
      "솔버 릴리스",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(
      within(screen.getByRole("list", { name: "차단 게이트" })).getAllByRole(
        "listitem",
      ),
    ).toHaveLength(8);
    expect(
      screen.getByRole("link", { name: /M3 진입 게이트 확인/ }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining("/docs/ko/m3-entry-gates.md"),
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "공정" }));
    expect(
      screen.getByRole("button", { name: "참조 워크플로 실행" }),
    ).toBeEnabled();
  });

  it("keeps English and Korean translation keys in parity", () => {
    expect(Object.keys(ko).sort()).toEqual(Object.keys(en).sort());
  });

  it("keeps Korean UI copy free from em dash punctuation", () => {
    expect(Object.values(ko).filter((message) => message.includes("\u2014"))).toEqual([]);
  });
});
