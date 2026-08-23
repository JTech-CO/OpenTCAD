import { describe, expect, it } from "vitest";
import {
  DEMO_DECK,
  drainCurrent,
  gateSweeps,
  profileFields,
  profileValue,
} from "./demo";

describe("deterministic reference fixtures", () => {
  it("labels the illustrative deck as non-executable", () => {
    expect(DEMO_DECK).toContain("static preview never executes input");
  });

  it("keeps every profile field finite and positive", () => {
    for (const field of profileFields) {
      for (let index = 0; index <= 80; index += 1) {
        const value = profileValue(field.id, index / 100);
        expect(Number.isFinite(value)).toBe(true);
        expect(value).toBeGreaterThan(0);
      }
    }
  });

  it("produces finite, non-negative reference curves", () => {
    for (const gateVoltage of gateSweeps) {
      for (let index = 0; index <= 12; index += 1) {
        const current = drainCurrent(gateVoltage, index / 10);
        expect(Number.isFinite(current)).toBe(true);
        expect(current).toBeGreaterThanOrEqual(0);
      }
    }
  });
});
