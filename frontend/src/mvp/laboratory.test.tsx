import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { Calculator } from "./Calculator";
import { SolverPanel } from "./SolverPanel";
import { defaultMos, mosPoint, mosRecord, parseMosRecord, validateMos } from "./models";
import { consumeExperiment, decodeSolverResult, defaultPn, PN_MODEL, validatePn } from "./solver-client";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); window.localStorage.clear(); window.history.replaceState(null, "", "/"); });
describe("actual analytical model", () => {
  it("matches a stated SI benchmark and geometric scaling", () => {
    const point = mosPoint(defaultMos);
    expect(point.thresholdV).toBeCloseTo(.1963499970604936, 12);
    expect(point.currentA).toBeCloseTo(.0005627096459489536, 14);
    expect(point.coxFm2).toBeCloseTo(.001726566623496, 14);
    expect(mosPoint({...defaultMos, widthUm: 20}).currentA / point.currentA).toBeCloseTo(2, 12);
    expect(mosPoint({...defaultMos, lengthUm: 4}).currentA / point.currentA).toBeCloseTo(.5, 12);
    expect(mosPoint({...defaultMos, bodyV: 1}).thresholdV).toBeGreaterThan(point.thresholdV);
    expect(mosPoint({...defaultMos, oxideNm: 40}).thresholdV).toBeGreaterThan(point.thresholdV);
    expect(mosPoint({...defaultMos, dopingCm3: 2e16}).thresholdV).toBeGreaterThan(point.thresholdV);
    expect(mosPoint(defaultMos, 0, 1).currentA).toBe(0);
    expect(mosPoint(defaultMos, 2, 0).currentA).toBe(0);
  });
  it("is continuous at saturation and has the reported transconductance", () => {
    const p = mosPoint(defaultMos), edge = defaultMos.gateV - p.thresholdV;
    expect(mosPoint(defaultMos, 2, edge-1e-8).currentA).toBeCloseTo(mosPoint(defaultMos, 2, edge+1e-8).currentA, 12);
    const derivative = (mosPoint(defaultMos, 2+1e-5).currentA - mosPoint(defaultMos, 2-1e-5).currentA) / 2e-5;
    expect(derivative).toBeCloseTo(p.gmS, 10);
  });
  it("rejects invalid input and recomputes rather than trusting saved results", () => {
    for (const value of [{...defaultMos, gateV: NaN}, {...defaultMos, widthUm: 0}, {...defaultMos, script: "code"}]) expect(() => validateMos(value)).toThrow();
    const record = mosRecord(defaultMos); record.point.currentA = 999;
    expect(mosPoint(parseMosRecord(JSON.stringify(record))).currentA).not.toBe(999);
  });
  it.each(["en", "ko"] as const)("updates visible current and plots from input in %s", locale => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    render(<Calculator locale={locale} />);
    const before = screen.getByTestId("calculated-current").textContent;
    const plots = [...document.querySelectorAll("polyline")].map(p => p.getAttribute("points"));
    fireEvent.change(screen.getByRole("spinbutton", {name: locale === "ko" ? /채널 폭/ : /Channel width/}), {target: {value: "20"}});
    expect(screen.getByTestId("calculated-current").textContent).not.toBe(before);
    // Auto-scaled curves can retain their shape. Physical numeric output is authoritative.
    expect(document.querySelectorAll("polyline")).toHaveLength(plots.length);
    fireEvent.change(screen.getByRole("spinbutton", {name: locale === "ko" ? /게이트-소스/ : /Gate-source/}), {target: {value: "1"}});
    expect(document.querySelector("polyline")!.getAttribute("points")).not.toBe(plots[0]);
    fireEvent.change(screen.getByRole("spinbutton", {name: locale === "ko" ? /채널 폭/ : /Channel width/}), {target: {value: ""}});
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTestId("calculated-current")).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
});

function resultFixture() {
  const x = Array.from({length: 201}, (_,i) => i / 100);
  return {format: "opentcad-solver-result", schemaVersion: 1, model: PN_MODEL, input: defaultPn,
    solver: "DEVSIM", solverVersion: "2.11.0", inputSha256: "a".repeat(64), templateSha256: "b".repeat(64), resultSha256: "c".repeat(64),
    environment: {python: "3.14.0", os: "Test", machine: "Test"}, constants: {temperatureK: 300, niCm3: 1e10, muN: 400, muP: 200, lifetimeS: 1e-6, epsilonFcm: 1e-12, qC: 1.6e-19, kJK: 1.38e-23},
    units: {x: "um", potential: "V", density: "cm^-3", current: "A"},
    iv: Array.from({length: 17}, (_,i) => [i * .4 / 16, i * 1e-10]), xUm: x,
    potentialV: x, equilibriumPotentialV: x, electronsCm3: x.map(() => 1e16), holesCm3: x.map(() => 1e4), netDopingCm3: x.map(() => 1e16),
    checks: {builtInExpectedV: .714, builtInComputedV: .714, builtInErrorV: 0, maxCurrentToleranceRatio: .01, nodeCount: 201}, productApproved: false};
}
describe("laboratory transport and interaction", () => {
  it("consumes only a loopback token and scrubs the fragment", () => {
    const replaceState = vi.fn();
    const location = {hash: "#experiment="+"A".repeat(43), protocol: "http:", hostname: "127.0.0.1", pathname: "/", search: ""} as Location;
    const history = {state: null, replaceState} as unknown as History;
    expect(consumeExperiment(location, history)).toBe("A".repeat(43));
    expect(replaceState).toHaveBeenCalledWith(null, "", "/#lab");
    expect(consumeExperiment({...location, hostname: "example.com"}, history)).toBeNull();
  });
  it("rejects wrong units, non-finite results, bad checks and unsafe inputs", () => {
    expect(decodeSolverResult(resultFixture()).solver).toBe("DEVSIM");
    for (const result of [{...resultFixture(), productApproved: true}, {...resultFixture(), units: {x: "m", potential: "V", density: "cm^-3", current: "A"}},
      {...resultFixture(), checks: {...resultFixture().checks, maxCurrentToleranceRatio: 2}}]) expect(() => decodeSolverResult(result)).toThrow();
    expect(() => validatePn({...defaultPn, intervals: 300})).toThrow();
    expect(() => validatePn({...defaultPn, command: "x"})).toThrow();
  });
  it("makes the calculator the introduction's primary action", () => {
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", {name: "Open device laboratory"})[0]);
    expect(screen.getByRole("heading", {name: "Instant NMOS calculator"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Run DEVSIM solve"})).toBeDisabled();
  });
  it("submits the exact input, polls a real-result contract and displays computed data", async () => {
    let id = "";
    const fetcher = vi.fn(async (_url: string, options: RequestInit) => {
      if (options.method === "POST") id = JSON.parse(options.body as string).requestId;
      return {ok: true, text: async () => JSON.stringify({requestId: id, state: options.method === "POST" ? "running" : "complete", inputSha256: "a".repeat(64), ...(options.method === "GET" ? {result: resultFixture()} : {})})};
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SolverPanel locale="en" token={"A".repeat(43)} />);
    fireEvent.click(screen.getByRole("button", {name: "Run DEVSIM solve"}));
    await screen.findByText("Solve complete", {}, {timeout: 3000});
    expect(screen.getByRole("img", {name: "Computed potential map"})).toBeInTheDocument();
    expect(JSON.parse(fetcher.mock.calls[0][1].body as string).input).toEqual(defaultPn);
    expect(fetcher.mock.calls[0][1].headers).toEqual(expect.objectContaining({Authorization: `Bearer ${"A".repeat(43)}`}));
    expect(screen.getByRole("button", {name: "Save inputs and results"})).toBeEnabled();
  });
  it("handles failed submission without fabricating a result or locking the form", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: false, status: 409}));
    render(<SolverPanel locale="ko" token={"A".repeat(43)} />);
    fireEvent.click(screen.getByRole("button", {name: "DEVSIM 해석 실행"}));
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("button", {name: "DEVSIM 해석 실행"})).toBeEnabled();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
