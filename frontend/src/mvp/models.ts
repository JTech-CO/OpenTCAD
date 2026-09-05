import { boundedNumber, exactRecord, parseWorkspaceJson } from "../m4/files";

export const MODEL = "long-channel-nmos-300K-v1";
// SI constants; doping is converted from cm^-3 to m^-3 at the boundary.
export const Q = 1.602176634e-19, KB = 1.380649e-23, EPS0 = 8.8541878128e-12;
export const parameters = {
  lengthUm: [1, 50, 0.1], widthUm: [1, 100, 0.1], oxideNm: [5, 100, 1],
  dopingCm3: [1e15, 1e17, 1e15], mobilityCm2Vs: [50, 1500, 10],
  flatbandV: [-2, 2, 0.05], gateV: [0, 5, 0.05], drainV: [0, 5, 0.05], bodyV: [0, 3, 0.05],
} as const;
export type Parameter = keyof typeof parameters;
export type MosInput = Record<Parameter, number>;
export const defaultMos: MosInput = { lengthUm: 2, widthUm: 10, oxideNm: 20, dopingCm3: 1e16,
  mobilityCm2Vs: 500, flatbandV: -0.8, gateV: 2, drainV: 1, bodyV: 0 };
export function validateMos(value: unknown): MosInput {
  const record = exactRecord(value, Object.keys(parameters));
  return Object.fromEntries(Object.entries(parameters).map(([key, [min, max]]) =>
    [key, boundedNumber(record[key], min, max)])) as MosInput;
}
export function mosPoint(p: MosInput, vg = p.gateV, vd = p.drainV) {
  validateMos(p);
  boundedNumber(vg, 0, 5); boundedNumber(vd, 0, 5);
  const cox = 3.9 * EPS0 / (p.oxideNm * 1e-9);
  // ni is a declared, fixed model constant, not a fitted process value.
  const phi = KB * 300 / Q * Math.log(p.dopingCm3 / 1e10);
  const gamma = Math.sqrt(2 * Q * 11.7 * EPS0 * p.dopingCm3 * 1e6) / cox;
  const thresholdV = p.flatbandV + 2 * phi + gamma * Math.sqrt(2 * phi + p.bodyV);
  const overdrive = Math.max(0, vg - thresholdV);
  const beta = p.mobilityCm2Vs * 1e-4 * cox * p.widthUm / p.lengthUm;
  const saturation = vd >= overdrive;
  const currentA = overdrive === 0 ? 0 : beta * (saturation ? overdrive ** 2 / 2 : overdrive * vd - vd ** 2 / 2);
  return { thresholdV, currentA, coxFm2: cox, gmS: overdrive === 0 ? 0 : beta * Math.min(vd, overdrive),
    region: overdrive === 0 ? "cutoff" as const : saturation ? "saturation" as const : "linear" as const };
}
export type Point = [number, number];
export function mosCurves(p: MosInput) {
  return { output: Array.from({ length: 101 }, (_, i): Point => [i / 20, mosPoint(p, p.gateV, i / 20).currentA * 1e3]),
    transfer: Array.from({ length: 101 }, (_, i): Point => [i / 20, mosPoint(p, i / 20, p.drainV).currentA * 1e3]) };
}
export function mosRecord(input: MosInput) {
  return { format: "opentcad-calculation", schemaVersion: 1, model: MODEL, temperatureK: 300,
    input: validateMos(input), units: { length: "um", oxide: "nm", doping: "cm^-3", current: "mA" },
    point: mosPoint(input), curves: mosCurves(input) };
}
export function parseMosRecord(source: string): MosInput {
  const record = exactRecord(parseWorkspaceJson(source), ["format", "schemaVersion", "model", "temperatureK", "input", "units", "point", "curves"]);
  if (record.format !== "opentcad-calculation" || record.schemaVersion !== 1 || record.model !== MODEL || record.temperatureK !== 300) throw new Error("model");
  // Results in imported records are never trusted. Recompute from validated inputs.
  return validateMos(record.input);
}
