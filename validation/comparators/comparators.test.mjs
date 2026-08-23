import assert from "node:assert/strict";
import test from "node:test";

import {
  buildValidationReport,
  compareCurve,
  compareExact,
  compareRepeatability,
  compareScalar,
  compareTopology,
  renderValidationReportHtml,
  sha256Hex,
} from "./index.mjs";

test("exact comparator detects a one-byte change", () => {
  const same = compareExact("structure\n", "structure\n");
  const changed = compareExact("structure\n", "structure!\n");

  assert.equal(same.pass, true);
  assert.equal(changed.pass, false);
  assert.equal(same.expectedHash, sha256Hex("structure\n"));
});

test("topology comparator treats named sets as unordered and counts as exact", () => {
  const expected = {
    nodes: 12,
    elements: 18,
    regions: 2,
    contacts: 3,
    materials: ["Silicon", "Oxide"],
    regionNames: ["body", "gate-oxide"],
    contactNames: ["source", "drain", "gate"],
  };
  const reordered = {
    ...expected,
    materials: ["Oxide", "Silicon"],
    contactNames: ["gate", "source", "drain"],
  };

  assert.equal(compareTopology(expected, reordered).pass, true);
  const changed = compareTopology(expected, { ...reordered, elements: 17 });
  assert.equal(changed.pass, false);
  assert.deepEqual(changed.differences[0], { field: "elements", expected: 18, actual: 17 });
});

test("scalar comparator uses the combined scale-aware tolerance gate", () => {
  assert.equal(compareScalar(100, 100.5, { absolute: 0.1, relative: 0.01 }).pass, true);
  assert.equal(compareScalar(100, 102, { absolute: 0.1, relative: 0.01 }).pass, false);
  assert.throws(() => compareScalar(Number.NaN, 1), /finite/);
});

test("curve comparator fails skipped points and curve drift independently", () => {
  const expected = [
    { x: 0, y: 0, status: "solved" },
    { x: 1, y: 10, status: "solved" },
  ];
  const close = [
    { x: 0, y: 0, status: "solved" },
    { x: 1, y: 10.05, status: "solved" },
  ];
  const skipped = [
    { x: 0, y: 0, status: "solved" },
    { x: 1, y: 10.05, status: "skipped" },
  ];

  const options = { xTolerance: { absolute: 0 }, yTolerance: { absolute: 0.1 } };
  assert.equal(compareCurve(expected, close, options).pass, true);
  assert.equal(compareCurve(expected, skipped, options).pass, false);
  assert.equal(compareCurve(expected, close.slice(0, 1), options).lengthMatches, false);
});

test("repeatability requires five samples and enforces the range", () => {
  const stable = compareRepeatability([10, 10.01, 9.99, 10, 10.005], { absolute: 0.03 });
  const sparse = compareRepeatability([10, 10], { absolute: 0.03 });
  const unstable = compareRepeatability([10, 10.2, 9.9, 10.1, 10], { absolute: 0.03 });

  assert.equal(stable.pass, true);
  assert.equal(sparse.pass, false);
  assert.equal(unstable.pass, false);
  assert.equal(stable.count, 5);
});

test("JSON and HTML reports are deterministic for caller-supplied metadata", () => {
  const report = buildValidationReport({
    caseId: "synthetic-case",
    baselineId: "pending-baseline",
    recordedAt: "2026-08-23T00:00:00.000Z",
    results: [compareScalar(1, 1, { absolute: 0 })],
    metadata: { engine: "none" },
  });
  assert.throws(
    () =>
      buildValidationReport({
        caseId: "synthetic-case",
        baselineId: "pending-baseline",
        recordedAt: "2026-08-23T00:00:00.000Z",
        results: [{ comparator: "unknown", pass: true }],
      }),
    /known comparator/,
  );
  const html = renderValidationReportHtml(report);

  assert.equal(report.status, "passed");
  assert.match(html, /OpenTCAD validation: synthetic-case/);
  assert.match(html, /PASS/);
  assert.doesNotMatch(html, /<script/);
});
