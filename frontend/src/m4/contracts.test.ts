/// <reference types="node" />
import { describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import { DEMO_DECK } from "../demo";
import { resultExamples } from "./examples";
import { decodeWorkspaceText, MAX_FILE_BYTES, parseWorkspaceJson, readWorkspaceBytes } from "./files";
import { newProject, parseProject, serializeProject, validateDeck, validateProject } from "./project";
import { initialMockRun, mockReducer } from "./mock-workflow";
import { compatibleResults, parseResult, resultFingerprint, sampleDifference, validateResult, type CurveResult } from "./results";

export const curveFixture = (name = "Run A"): CurveResult => ({
  format: "opentcad-result", schemaVersion: 1, kind: "iv", name, source: "unreviewed lab file",
  xUnit: "V", yUnit: "mA/um", points: [[0, 0], [0.5, 0.1], [1, 0.2]],
});
export const structureFixture = () => ({
  format: "opentcad-result", schemaVersion: 1, kind: "structure", name: "Structure A", source: "external",
  unit: "um", width: 1.2, height: 0.8,
  regions: [{ id: "body", material: "silicon", x: 0, y: 0, width: 1.2, height: 0.8 }],
});

describe("bounded workspace files", () => {
  it.each(['{"a":1,"a":2}', '{"a":1,"\\u0061":2}', '{"__proto__":{}}', '{"constructor":1}', '[1,]', '{"x":NaN}', '{"x":1e999}', '01', 'true false', '"\n"'])
    ("rejects ambiguous or hostile JSON %s", (source) => expect(() => parseWorkspaceJson(source)).toThrow());
  it("accepts escaped strings, arrays, booleans and null without a prototype", () => {
    expect(parseWorkspaceJson('{"value":[null,true,false,-1.2e3,"a\\\"b"]}')).toEqual({ value: [null, true, false, -1200, 'a"b'] });
    expect(Object.getPrototypeOf(parseWorkspaceJson('{"x":1}'))).toBeNull();
  });
  it("bounds nesting and file bytes before parsing or reading", async () => {
    expect(() => parseWorkspaceJson("[".repeat(20) + "0" + "]".repeat(20))).toThrow();
    expect(() => parseWorkspaceJson('"' + "x".repeat(MAX_FILE_BYTES) + '"')).toThrow();
    await expect(readWorkspaceBytes(new File(["x".repeat(MAX_FILE_BYTES + 1)], "big.json"))).rejects.toThrow();
  });
  it("rejects malformed UTF-8 and hashes exact bytes including BOM", async () => {
    expect(() => decodeWorkspaceText(new Uint8Array([255]).buffer)).toThrow();
    vi.stubGlobal("crypto", webcrypto);
    try {
      const plain = new TextEncoder().encode("{}").buffer;
      const withBom = new Uint8Array([239, 187, 191, 123, 125]).buffer;
      expect(decodeWorkspaceText(withBom)).toBe("{}");
      expect(await resultFingerprint(plain)).not.toBe(await resultFingerprint(withBom));
      expect(await resultFingerprint(plain)).toMatch(/^[a-f0-9]{64}$/u);
    } finally { vi.unstubAllGlobals(); }
  });
});

describe("project and illustrative deck contracts", () => {
  it("round trips project drafts without runtime authority or secrets", () => {
    const project = newProject();
    expect(parseProject(serializeProject(project))).toEqual(project);
    expect(() => validateProject({ ...project, productEnabled: true })).toThrow();
    expect(() => validateProject({ ...project, token: "private" })).toThrow();
    expect(() => validateProject({ ...project, name: "" })).toThrow();
    expect(() => validateProject({ ...project, bias: { ...project.bias, temperature: NaN } })).toThrow();
    expect(() => validateProject({ ...project, bias: { ...project.bias, gateVoltage: 11 } })).toThrow();
    expect(parseProject(serializeProject({ ...project, deck: "" })).deck).toBe("");
  });
  it("accepts the reference syntax and preserves comments inside quotes", () => {
    expect(validateDeck(DEMO_DECK)).toEqual([]);
    expect(validateDeck(DEMO_DECK.replace('title "OpenTCAD planar NMOS reference"', 'title "quoted # title" # comment'))).toEqual([]);
  });
  it.each([
    ["", "deckEmpty"], ["x".repeat(65537), "deckLimit"],
    ['title "unclosed', "deckQuotes"], ["system rm", "deckExternal"],
    ["grid x=0 spacing=0", "deckNumeric"], ["grid x=0 x=1 spacing=1", "deckParameters"],
    ["implant boron dose=1e999 energy=1", "deckNumeric"],
    ["deposit oxide", "deckParameters"], ["title x", "deckRequired"],
  ])("reports bounded diagnostics for %s", (deck, code) => {
    expect(validateDeck(deck)).toEqual(expect.arrayContaining([expect.objectContaining({ code, severity: "error" })]));
  });
  it("does not hide a blocking error behind the warning display limit", () => {
    const issues = validateDeck(DEMO_DECK + "unknown\n".repeat(200) + "system anything");
    expect(issues).toHaveLength(100);
    expect(issues.some((issue) => issue.code === "deckExternal")).toBe(true);
  });
});

describe("result import and comparison", () => {
  it("validates every downloadable format example without execution authority", () => {
    for (const example of resultExamples) {
      expect(parseResult(JSON.stringify(example), "example.json")).toEqual(example);
      expect(example.source).toContain("not solver output");
    }
  });
  it("imports supported CSV and JSON without accepting approval fields", () => {
    expect(parseResult("vd_v,id_ma_per_um\n0,0\n1,0.2\n", "curve.csv").kind).toBe("iv");
    expect(parseResult("depth_um,concentration_cm-3\n0,1e20\n1,1e15", "profile.csv").kind).toBe("profile");
    expect(parseResult(JSON.stringify(structureFixture()), "device.json").kind).toBe("structure");
    expect(() => validateResult({ ...curveFixture(), verified: true })).toThrow();
    expect(() => parseResult("x,y\n0,1\n1,2", "unknown.csv")).toThrow();
    expect(() => parseResult("vd_v,id_ma_per_um\n0,=CMD()\n1,2", "formula.csv")).toThrow();
    expect(() => parseResult("anything", "result.str")).toThrow();
  });
  it("rejects non-finite, wrong-unit, unsorted and excessive points", () => {
    for (const change of [
      { points: [[0, 0], [0, 1]] }, { points: [[1, 1], [0, 2]] },
      { points: [[0, 0], [1, Infinity]] }, { points: Array.from({ length: 2001 }, (_, i) => [i, i]) },
      { xUnit: "m" }, { yUnit: "A" }, { kind: "profile", xUnit: "um", yUnit: "cm^-3", points: [[0, 0], [1, 1]] },
    ]) expect(() => validateResult({ ...curveFixture(), ...change })).toThrow();
  });
  it("bounds structure regions and rejects duplicate identities", () => {
    const fixture = structureFixture();
    expect(() => validateResult({ ...fixture, regions: [fixture.regions[0], fixture.regions[0]] })).toThrow();
    expect(() => validateResult({ ...fixture, regions: [{ ...fixture.regions[0], width: 2 }] })).toThrow();
    expect(() => validateResult({ ...fixture, regions: [{ ...fixture.regions[0], x: -1 }] })).toThrow();
  });
  it("compares matching coordinates only, with no interpolation or acceptance", () => {
    const a = curveFixture(), b = curveFixture("B"); b.points = [[0, 0.1], [0.5, 0.2], [1, 0.3]];
    const delta = sampleDifference(a, b)!;
    expect(delta.count).toBe(3); expect(delta.maxAbsolute).toBeCloseTo(0.1);
    expect(delta.meanAbsolute).toBeCloseTo(0.1);
    expect(compatibleResults(a, { ...b, xUnit: "um" })).toBe(false);
    expect(sampleDifference(a, { ...b, yUnit: "cm^-3" })).toBeNull();
    b.points[1][0] = 0.6; expect(sampleDifference(a, b)).toBeNull();
    expect(compatibleResults(a, validateResult(structureFixture()))).toBe(false);
  });
});

describe("mock lifecycle fencing", () => {
  it.each([0, 1, 2, 3, 4])("cancels and recovers at phase %i without accepting stale ticks", (step) => {
    let run = mockReducer(initialMockRun, { type: "start" });
    for (let index = 0; index < step; index++) run = mockReducer(run, { type: "tick", generation: run.generation });
    const oldGeneration = run.generation;
    const interrupted = mockReducer(run, { type: "interrupt" });
    expect(mockReducer(interrupted, { type: "start" })).toBe(interrupted);
    expect(mockReducer(interrupted, { type: "tick", generation: oldGeneration })).toBe(interrupted);
    const recovered = mockReducer(interrupted, { type: "recover" });
    expect(recovered.step).toBe(step);
    expect(mockReducer(recovered, { type: "tick", generation: oldGeneration })).toBe(recovered);
    const cancelled = mockReducer(recovered, { type: "cancel" });
    expect(cancelled.phase).toBe("cancelled");
    expect(mockReducer(cancelled, { type: "recover" })).toBe(cancelled);
    expect(mockReducer(cancelled, { type: "tick", generation: recovered.generation })).toBe(cancelled);
  });
  it("completes once and bounds history", () => {
    let run = initialMockRun;
    for (let repeat = 0; repeat < 10; repeat++) {
      run = mockReducer(run, { type: "start" });
      for (let step = 0; step < 5; step++) run = mockReducer(run, { type: "tick", generation: run.generation });
      expect(run.phase).toBe("complete");
      expect(mockReducer(run, { type: "tick", generation: run.generation })).toBe(run);
    }
    expect(run.history).toHaveLength(20);
  });
});
