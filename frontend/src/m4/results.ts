import { boundedNumber, boundedText, exactRecord, MAX_FILE_BYTES, parseWorkspaceJson, WorkspaceFileError } from "./files";

export interface CurveResult {
  format: "opentcad-result"; schemaVersion: 1; kind: "iv" | "profile";
  name: string; source: string; xUnit: "V" | "um"; yUnit: "mA/um" | "cm^-3";
  points: [number, number][];
}
export interface ResultRegion { id: string; material: string; x: number; y: number; width: number; height: number }
export interface StructureResult {
  format: "opentcad-result"; schemaVersion: 1; kind: "structure";
  name: string; source: string; unit: "um"; width: number; height: number;
  regions: ResultRegion[];
}
export type WorkspaceResult = CurveResult | StructureResult;
export interface ImportedResult { id: string; filename: string; sha256: string | null; data: WorkspaceResult; verified: false }

export function validateResult(value: unknown): WorkspaceResult {
  const kind = (value as { kind?: unknown } | null)?.kind;
  const result = exactRecord(value, kind === "structure"
    ? ["format", "schemaVersion", "kind", "name", "source", "unit", "width", "height", "regions"]
    : ["format", "schemaVersion", "kind", "name", "source", "xUnit", "yUnit", "points"]);
  if (result.format !== "opentcad-result" || result.schemaVersion !== 1) throw new WorkspaceFileError();
  const identity = { format: "opentcad-result" as const, schemaVersion: 1 as const,
    name: boundedText(result.name, 80), source: boundedText(result.source, 200) };
  if (kind === "structure") {
    if (result.unit !== "um" || !Array.isArray(result.regions) || result.regions.length < 1 || result.regions.length > 64) throw new WorkspaceFileError();
    const width = boundedNumber(result.width, 1e-9, 1e6), height = boundedNumber(result.height, 1e-9, 1e6);
    const ids = new Set<string>();
    const regions = result.regions.map((item) => {
      const region = exactRecord(item, ["id", "material", "x", "y", "width", "height"]);
      const id = boundedText(region.id, 60);
      if (ids.has(id)) throw new WorkspaceFileError();
      ids.add(id);
      const x = boundedNumber(region.x, 0, width), y = boundedNumber(region.y, 0, height);
      const regionWidth = boundedNumber(region.width, 1e-12, width), regionHeight = boundedNumber(region.height, 1e-12, height);
      if (x + regionWidth > width + width * 1e-12 || y + regionHeight > height + height * 1e-12) throw new WorkspaceFileError();
      return { id, material: boundedText(region.material, 60), x, y, width: regionWidth, height: regionHeight };
    });
    return { ...identity, kind, unit: "um", width, height, regions };
  }
  if (kind !== "iv" && kind !== "profile") throw new WorkspaceFileError();
  const xUnit = kind === "iv" ? "V" : "um", yUnit = kind === "iv" ? "mA/um" : "cm^-3";
  if (result.xUnit !== xUnit || result.yUnit !== yUnit || !Array.isArray(result.points)
    || result.points.length < 2 || result.points.length > 2000) throw new WorkspaceFileError();
  let previous = -Infinity;
  const points = result.points.map((point): [number, number] => {
    if (!Array.isArray(point) || point.length !== 2) throw new WorkspaceFileError();
    const x = boundedNumber(point[0], kind === "profile" ? 0 : -1e6, 1e6);
    const y = boundedNumber(point[1], kind === "profile" ? 1e-30 : -1e30, 1e30);
    if (x <= previous) throw new WorkspaceFileError();
    previous = x;
    return [x, y];
  });
  return { ...identity, kind, xUnit, yUnit, points };
}

export function parseResult(source: string, filename: string): WorkspaceResult {
  if (new TextEncoder().encode(source).length > MAX_FILE_BYTES) throw new WorkspaceFileError();
  if (filename.toLowerCase().endsWith(".json")) return validateResult(parseWorkspaceJson(source));
  if (!filename.toLowerCase().endsWith(".csv")) throw new WorkspaceFileError();
  const lines = source.replace(/^\uFEFF/u, "").trim().split(/\r?\n/u);
  const header = lines.shift()?.trim();
  const kind = header === "vd_v,id_ma_per_um" ? "iv" : header === "depth_um,concentration_cm-3" ? "profile" : null;
  if (!kind || lines.length > 2000) throw new WorkspaceFileError();
  const points = lines.map((line) => {
    const parts = line.split(",").map((part) => part.trim());
    if (parts.length !== 2 || parts.some((part) => !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/iu.test(part))) throw new WorkspaceFileError();
    return parts.map(Number);
  });
  return validateResult({ format: "opentcad-result", schemaVersion: 1, kind,
    name: filename.slice(0, 80), source: filename.slice(0, 200),
    xUnit: kind === "iv" ? "V" : "um", yUnit: kind === "iv" ? "mA/um" : "cm^-3", points });
}

export function compatibleResults(a: WorkspaceResult, b: WorkspaceResult): boolean {
  if (a.kind === "structure" || b.kind === "structure") {
    return a.kind === "structure" && b.kind === "structure" && a.unit === b.unit;
  }
  return a.kind === b.kind && a.xUnit === b.xUnit && a.yUnit === b.yUnit;
}

/** Only identical sample coordinates are compared; never silently interpolate. */
export function sampleDifference(a: CurveResult, b: CurveResult): { count: number; maxAbsolute: number; meanAbsolute: number } | null {
  if (!compatibleResults(a, b) || a.points.length !== b.points.length
    || a.points.some((point, i) => point[0] !== b.points[i][0])) return null;
  const deltas = a.points.map((point, i) => Math.abs(point[1] - b.points[i][1]));
  return { count: deltas.length, maxAbsolute: Math.max(...deltas), meanAbsolute: deltas.reduce((sum, value) => sum + value, 0) / deltas.length };
}

export async function resultFingerprint(source: ArrayBuffer): Promise<string | null> {
  try {
    const digest = await globalThis.crypto.subtle.digest("SHA-256", source);
    return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
  } catch { return null; }
}
