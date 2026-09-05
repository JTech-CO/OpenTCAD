import { boundedNumber, exactRecord } from "../m4/files";
export const PN_MODEL = "devsim-pn-1d-300K-v1";
export const pnLimits = { lengthUm: [1, 10], acceptorsCm3: [1e15, 1e17], donorsCm3: [1e15, 1e17], areaUm2: [1, 100], voltageV: [0, 0.5] } as const;
export type PnInput = Record<keyof typeof pnLimits, number> & { intervals: number };
export const defaultPn: PnInput = { lengthUm: 2, acceptorsCm3: 1e16, donorsCm3: 1e16, areaUm2: 10, voltageV: .4, intervals: 200 };
export function validatePn(value: unknown): PnInput {
  const record = exactRecord(value, [...Object.keys(pnLimits), "intervals"]);
  const input = Object.fromEntries(Object.entries(pnLimits).map(([key, [lo, hi]]) => [key, boundedNumber(record[key], lo, hi)]));
  if (![100, 200, 400].includes(record.intervals as number)) throw new Error("mesh");
  return { ...input, intervals: record.intervals } as PnInput;
}
export function consumeExperiment(location: Location = window.location, history: History = window.history): string | null {
  if (!location.hash.startsWith("#experiment=")) return null;
  const token = location.hash.slice(12);
  history.replaceState(history.state, "", `${location.pathname}${location.search}#lab`);
  if (location.protocol !== "http:" || !["localhost", "127.0.0.1", "[::1]"].includes(location.hostname) || !/^[\w-]{43}$/u.test(token)) return null;
  return token;
}
export interface SolverResult {
  format: "opentcad-solver-result"; schemaVersion: 1; model: typeof PN_MODEL; input: PnInput;
  solver: "DEVSIM"; solverVersion: string; inputSha256: string; templateSha256: string; resultSha256: string;
  environment: Record<string, string>; constants: Record<string, number>; units: Record<string, string>;
  iv: [number, number][]; xUm: number[]; potentialV: number[]; equilibriumPotentialV: number[];
  electronsCm3: number[]; holesCm3: number[]; netDopingCm3: number[];
  checks: Record<string, number>; productApproved: false;
}
export function decodeSolverResult(value: unknown): SolverResult {
  const r = exactRecord(value, ["format", "schemaVersion", "model", "input", "solver", "solverVersion", "inputSha256", "templateSha256", "resultSha256", "environment", "constants", "units", "iv", "xUm", "potentialV", "equilibriumPotentialV", "electronsCm3", "holesCm3", "netDopingCm3", "checks", "productApproved"]);
  const input = validatePn(r.input);
  if (r.format !== "opentcad-solver-result" || r.schemaVersion !== 1 || r.model !== PN_MODEL || r.solver !== "DEVSIM" || r.solverVersion !== "2.11.0" || r.productApproved !== false) throw new Error("result-format");
  for (const key of ["inputSha256", "templateSha256", "resultSha256"]) if (typeof r[key] !== "string" || !/^[a-f0-9]{64}$/u.test(r[key])) throw new Error("digest");
  const units = exactRecord(r.units, ["x", "potential", "density", "current"]);
  if (units.x !== "um" || units.potential !== "V" || units.density !== "cm^-3" || units.current !== "A") throw new Error("units");
  const env = exactRecord(r.environment, ["python", "os", "machine"]);
  if (Object.values(env).some(v => typeof v !== "string" || v.length > 80)) throw new Error("environment");
  for (const [field, positive] of [["xUm", false], ["potentialV", false], ["equilibriumPotentialV", false], ["electronsCm3", true], ["holesCm3", true], ["netDopingCm3", false]] as const) {
    const series = r[field];
    if (!Array.isArray(series) || series.length !== input.intervals + 1) throw new Error("nodes");
    for (const v of series) boundedNumber(v, positive ? Number.MIN_VALUE : -1e30, 1e30);
  }
  const x = r.xUm as number[];
  if (Math.abs(x[0]) > 1e-12 || Math.abs(x.at(-1)! - input.lengthUm) > 1e-9 || x.some((v,i) => i > 0 && v <= x[i-1])) throw new Error("coordinates");
  if (!Array.isArray(r.iv) || r.iv.length !== Math.max(1, Math.ceil(input.voltageV / .025)) + 1) throw new Error("iv");
  r.iv.forEach((point, i) => {
    if (!Array.isArray(point) || point.length !== 2) throw new Error("point");
    boundedNumber(point[0], 0, .5); boundedNumber(point[1], -1e10, 1e10);
    if (Math.abs(point[0] - input.voltageV * i / ((r.iv as unknown[]).length - 1)) > 1e-12) throw new Error("sweep");
  });
  const checks = exactRecord(r.checks, ["builtInExpectedV", "builtInComputedV", "builtInErrorV", "maxCurrentToleranceRatio", "nodeCount"]);
  Object.values(checks).forEach(v => boundedNumber(v, 0, 1e6));
  if (Number(checks.builtInErrorV) > 1e-7 || Number(checks.maxCurrentToleranceRatio) > 1 || checks.nodeCount !== x.length) throw new Error("checks");
  const constants = exactRecord(r.constants, ["temperatureK", "niCm3", "muN", "muP", "lifetimeS", "epsilonFcm", "qC", "kJK"]);
  Object.values(constants).forEach(v => boundedNumber(v, Number.MIN_VALUE, 1e30));
  return r as unknown as SolverResult;
}
export interface LabJob { requestId: string; inputSha256: string; state: "running" | "complete" | "cancelled" | "failed"; result?: SolverResult; error?: string }
export function decodeJob(value: unknown, id: string): LabJob {
  if (!value || typeof value !== "object") throw new Error("job");
  const r = value as LabJob;
  if (r.requestId !== id || !["running", "complete", "cancelled", "failed"].includes(r.state)) throw new Error("job");
  if (r.state === "complete") return { ...r, result: decodeSolverResult(r.result) };
  return r;
}
export async function labRequest(token: string, path: string, body?: unknown, signal?: AbortSignal): Promise<unknown> {
  if (!/^[\w-]{43}$/u.test(token) || !path.startsWith("/v1/lab/")) throw new Error("authority");
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", abort, {once: true});
  const timer = window.setTimeout(abort, 10000);
  try {
  const response = await fetch(path, { method: body === undefined ? "GET" : "POST", credentials: "omit", redirect: "error", cache: "no-store", signal: controller.signal,
    headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const text = await response.text();
  if (text.length > 1_048_576) throw new Error("response-size");
  return JSON.parse(text);
  } finally { window.clearTimeout(timer); signal?.removeEventListener("abort", abort); }
}
