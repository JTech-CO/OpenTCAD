import { describe, expect, it, vi } from "vitest";
import {
  consumeLocalBootstrap,
  decodeLocalProductStatus,
  fetchLocalProductStatus,
} from "./local-service";

const token = "A".repeat(43);
const validStatus = {
  schemaVersion: 1,
  serviceState: "ready",
  executionState: "blocked",
  manifestSha256: "a".repeat(64),
  backend: null,
  blockedGates: ["runtime-adapters", "solver-release"],
  recoveryState: "not-applicable",
  schedulerState: "not-started",
};

describe("local service boundary", () => {
  it("consumes a loopback bootstrap once and scrubs the fragment", () => {
    const replaceState = vi.fn();
    const result = consumeLocalBootstrap(
      {
        hash: `#local=${token}`,
        protocol: "http:",
        hostname: "127.0.0.1",
        pathname: "/",
        search: "",
      } as Location,
      { state: null, replaceState } as unknown as History,
    );

    expect(result).toEqual({ token });
    expect(replaceState).toHaveBeenCalledWith(null, "", "/#workspace");
  });

  it("rejects a bootstrap on a public origin while still scrubbing it", () => {
    const replaceState = vi.fn();
    expect(
      consumeLocalBootstrap(
        {
          hash: `#local=${token}`,
          protocol: "https:",
          hostname: "jtech-co.github.io",
          pathname: "/OpenTCAD/",
          search: "",
        } as Location,
        { state: null, replaceState } as unknown as History,
      ),
    ).toBeNull();
    expect(replaceState).toHaveBeenCalledOnce();
  });

  it("decodes only the exact versioned status shape", () => {
    expect(decodeLocalProductStatus(validStatus).executionState).toBe("blocked");
    expect(() => decodeLocalProductStatus({ ...validStatus, path: "C:/secret" })).toThrow(
      "local-status-invalid",
    );
    expect(() =>
      decodeLocalProductStatus({ ...validStatus, executionState: "authorized" }),
    ).toThrow("local-status-invalid");
    expect(() =>
      decodeLocalProductStatus({
        ...validStatus,
        blockedGates: ["runtime-adapters", "unknown-gate"],
      }),
    ).toThrow("local-status-invalid");
  });

  it("uses only same-origin authenticated no-store status fetch", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      headers: { get: () => "application/json; charset=utf-8" },
      json: async () => validStatus,
    } as unknown as Response);

    await expect(fetchLocalProductStatus({ token }, fetcher)).resolves.toEqual(
      validStatus,
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/v1/status",
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        redirect: "error",
        credentials: "omit",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${token}`,
        },
      }),
    );
  });
});
