import { createHash } from "node:crypto";

export const COMPARATOR_IDS = Object.freeze([
  "exact-hash",
  "topology",
  "scalar",
  "curve",
  "repeatability",
]);

const countKeys = ["nodes", "elements", "regions", "contacts"];
const setKeys = ["materials", "regionNames", "contactNames"];

function requireFinite(value, label) {
  if (!Number.isFinite(value)) throw new TypeError(`${label} must be finite.`);
}

function requireNonNegative(value, label) {
  requireFinite(value, label);
  if (value < 0) throw new RangeError(`${label} must be non-negative.`);
}

function normalizeTolerance(tolerance = {}) {
  const absolute = tolerance.absolute ?? 0;
  const relative = tolerance.relative ?? 0;
  requireNonNegative(absolute, "absolute tolerance");
  requireNonNegative(relative, "relative tolerance");
  return { absolute, relative };
}

function bytes(value, label) {
  if (typeof value === "string") return Buffer.from(value, "utf8");
  if (value instanceof ArrayBuffer) return Buffer.from(value);
  if (ArrayBuffer.isView(value)) {
    return Buffer.from(value.buffer, value.byteOffset, value.byteLength);
  }
  throw new TypeError(`${label} must be a string, ArrayBuffer, or typed array.`);
}

function sortedStrings(value, label) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new TypeError(`${label} must be an array of strings.`);
  }
  if (new Set(value).size !== value.length) throw new Error(`${label} contains duplicates.`);
  return [...value].sort((left, right) => left.localeCompare(right));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function sha256Hex(value) {
  return createHash("sha256").update(bytes(value, "artifact")).digest("hex");
}

export function compareExact(expected, actual) {
  const expectedBytes = bytes(expected, "expected artifact");
  const actualBytes = bytes(actual, "actual artifact");
  const expectedHash = sha256Hex(expectedBytes);
  const actualHash = sha256Hex(actualBytes);

  return {
    comparator: "exact-hash",
    pass: expectedHash === actualHash,
    expectedHash,
    actualHash,
    expectedBytes: expectedBytes.byteLength,
    actualBytes: actualBytes.byteLength,
  };
}

export function compareTopology(expected, actual) {
  const differences = [];

  for (const key of countKeys) {
    if (!Number.isInteger(expected[key]) || expected[key] < 0) {
      throw new TypeError(`expected.${key} must be a non-negative integer.`);
    }
    if (!Number.isInteger(actual[key]) || actual[key] < 0) {
      throw new TypeError(`actual.${key} must be a non-negative integer.`);
    }
    if (expected[key] !== actual[key]) {
      differences.push({ field: key, expected: expected[key], actual: actual[key] });
    }
  }

  for (const key of setKeys) {
    const expectedValues = sortedStrings(expected[key], `expected.${key}`);
    const actualValues = sortedStrings(actual[key], `actual.${key}`);
    if (JSON.stringify(expectedValues) !== JSON.stringify(actualValues)) {
      differences.push({ field: key, expected: expectedValues, actual: actualValues });
    }
  }

  return {
    comparator: "topology",
    pass: differences.length === 0,
    differences,
  };
}

export function compareScalar(expected, actual, tolerance = {}) {
  requireFinite(expected, "expected scalar");
  requireFinite(actual, "actual scalar");
  const normalized = normalizeTolerance(tolerance);
  const absoluteDifference = Math.abs(actual - expected);
  const scale = Math.max(Math.abs(expected), Math.abs(actual));
  const relativeDifference = scale === 0 ? 0 : absoluteDifference / scale;
  const allowedDifference = Math.max(normalized.absolute, normalized.relative * scale);

  return {
    comparator: "scalar",
    pass: absoluteDifference <= allowedDifference,
    expected,
    actual,
    absoluteDifference,
    relativeDifference,
    tolerance: normalized,
    allowedDifference,
  };
}

export function compareCurve(expectedPoints, actualPoints, options = {}) {
  if (!Array.isArray(expectedPoints) || !Array.isArray(actualPoints)) {
    throw new TypeError("Curve inputs must be arrays.");
  }

  const xTolerance = normalizeTolerance(options.xTolerance);
  const yTolerance = normalizeTolerance(options.yTolerance);
  const requireSolved = options.requireSolved ?? true;
  const pointResults = [];
  const lengthMatches = expectedPoints.length === actualPoints.length;
  const comparedLength = Math.min(expectedPoints.length, actualPoints.length);

  for (let index = 0; index < comparedLength; index += 1) {
    const expected = expectedPoints[index];
    const actual = actualPoints[index];
    if (!expected || !actual || typeof expected !== "object" || typeof actual !== "object") {
      throw new TypeError(`Curve point ${index} must be an object.`);
    }
    requireFinite(expected.x, `expected curve x at ${index}`);
    requireFinite(expected.y, `expected curve y at ${index}`);
    requireFinite(actual.x, `actual curve x at ${index}`);
    requireFinite(actual.y, `actual curve y at ${index}`);

    const expectedStatus = expected.status ?? "solved";
    const actualStatus = actual.status ?? "solved";
    const statusPass = expectedStatus === actualStatus && (!requireSolved || actualStatus === "solved");
    const x = compareScalar(expected.x, actual.x, xTolerance);
    const y = compareScalar(expected.y, actual.y, yTolerance);

    pointResults.push({
      index,
      pass: statusPass && x.pass && y.pass,
      expectedStatus,
      actualStatus,
      statusPass,
      x,
      y,
    });
  }

  return {
    comparator: "curve",
    pass: lengthMatches && pointResults.every(({ pass }) => pass),
    expectedPoints: expectedPoints.length,
    actualPoints: actualPoints.length,
    lengthMatches,
    requireSolved,
    xTolerance,
    yTolerance,
    maxAbsoluteYDifference: Math.max(0, ...pointResults.map(({ y }) => y.absoluteDifference)),
    maxRelativeYDifference: Math.max(0, ...pointResults.map(({ y }) => y.relativeDifference)),
    pointResults,
  };
}

export function compareRepeatability(samples, tolerance = {}) {
  if (!Array.isArray(samples)) throw new TypeError("Repeatability samples must be an array.");
  const minSamples = tolerance.minSamples ?? 5;
  if (!Number.isInteger(minSamples) || minSamples < 2) {
    throw new RangeError("minSamples must be an integer of at least 2.");
  }
  samples.forEach((sample, index) => requireFinite(sample, `repeatability sample ${index}`));

  const normalized = normalizeTolerance(tolerance);
  const count = samples.length;
  const mean = count === 0 ? null : samples.reduce((sum, sample) => sum + sample, 0) / count;
  const minimum = count === 0 ? null : Math.min(...samples);
  const maximum = count === 0 ? null : Math.max(...samples);
  const range = count === 0 ? null : maximum - minimum;
  const standardDeviation =
    count === 0
      ? null
      : Math.sqrt(samples.reduce((sum, sample) => sum + (sample - mean) ** 2, 0) / count);
  const scale = mean === null ? 0 : Math.abs(mean);
  const allowedRange = Math.max(normalized.absolute, normalized.relative * scale);

  return {
    comparator: "repeatability",
    pass: count >= minSamples && range <= allowedRange,
    count,
    minSamples,
    mean,
    minimum,
    maximum,
    range,
    relativeRange: mean === null || mean === 0 ? null : range / Math.abs(mean),
    standardDeviation,
    tolerance: normalized,
    allowedRange,
  };
}

export function buildValidationReport({ caseId, baselineId, recordedAt, results, metadata = {} }) {
  if (typeof caseId !== "string" || caseId.length === 0) throw new TypeError("caseId is required.");
  if (typeof baselineId !== "string" || baselineId.length === 0) {
    throw new TypeError("baselineId is required.");
  }
  if (typeof recordedAt !== "string" || Number.isNaN(Date.parse(recordedAt))) {
    throw new TypeError("recordedAt must be an ISO date-time string supplied by the caller.");
  }
  if (!Array.isArray(results) || results.some((result) => typeof result?.pass !== "boolean")) {
    throw new TypeError("results must contain comparator result objects.");
  }
  if (results.some(({ comparator }) => !COMPARATOR_IDS.includes(comparator))) {
    throw new TypeError("results must use a known comparator id.");
  }

  return {
    schemaVersion: 1,
    caseId,
    baselineId,
    recordedAt,
    status: results.every(({ pass }) => pass) ? "passed" : "failed",
    metadata,
    results,
  };
}

export function renderValidationReportHtml(report) {
  const title = `OpenTCAD validation: ${report.caseId}`;
  const rows = report.results
    .map(
      (result) =>
        `<tr><td>${escapeHtml(result.comparator)}</td><td>${result.pass ? "PASS" : "FAIL"}</td></tr>`,
    )
    .join("");
  const json = escapeHtml(JSON.stringify(report, null, 2));

  return [
    "<!doctype html>",
    '<html lang="en">',
    "<head>",
    '<meta charset="utf-8">',
    `<title>${escapeHtml(title)}</title>`,
    "</head>",
    "<body>",
    `<h1>${escapeHtml(title)}</h1>`,
    `<p>Status: <strong>${escapeHtml(report.status.toUpperCase())}</strong></p>`,
    `<p>Baseline: <code>${escapeHtml(report.baselineId)}</code></p>`,
    `<table><thead><tr><th>Comparator</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table>`,
    `<pre>${json}</pre>`,
    "</body>",
    "</html>",
    "",
  ].join("\n");
}
