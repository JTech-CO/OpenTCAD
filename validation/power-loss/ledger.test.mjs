import test from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import {
  POWER_LOSS_CUT_POINTS,
  PowerLossLedgerError,
  parseAndValidatePhysicalPowerLossLedger,
  validatePhysicalPowerLossLedger,
} from "./ledger.mjs";

const hash = (character) => character.repeat(64);
const boot = (cutPoint, repetition, side) =>
  `${cutPoint}-${repetition}-${side}`;

function ledger() {
  const runs = POWER_LOSS_CUT_POINTS.flatMap((cutPoint) =>
    Array.from({ length: 10 }, (_, index) => {
      const repetition = index + 1;
      return {
        runId: randomUUID(),
        cutPoint,
        repetition,
        abruptPowerCut: true,
        armedAt: "2026-09-01T00:00:00Z",
        rebootObservedAt: "2026-09-01T00:01:00Z",
        preCutBootId: boot(cutPoint, repetition, "before"),
        postCutBootId: boot(cutPoint, repetition, "after"),
        preCutMarkerSha256: hash("1"),
        hostLogSha256: hash("2"),
        observerRecordSha256: hash("3"),
        sqlite: {
          control: { quickCheck: "ok", integrityCheck: "ok" },
          state: { quickCheck: "ok", integrityCheck: "ok" },
          fence: { quickCheck: "ok", integrityCheck: "ok" },
        },
        partialPublicationAccepted: false,
        rollbackViolation: false,
        recoverySynthesizedSuccess: false,
        unexplainedManagedObjects: 0,
      };
    }),
  );
  return {
    schemaVersion: 2,
    evidenceId: randomUUID(),
    revision: "a".repeat(40),
    activationManifestSha256: hash("4"),
    runtimeGrantsSha256: hash("5"),
    imageLockSha256: hash("6"),
    platform: "windows",
    architecture: "amd64",
    osVersion: "qualification-host",
    filesystem: "qualification-filesystem",
    storage: {
      model: "disposable-test-storage",
      firmware: "recorded-firmware",
      serialSha256: hash("7"),
      controller: "recorded-controller",
      writeCacheConfiguration: "recorded-cache-policy",
    },
    powerController: {
      kind: "pdu",
      model: "independent-test-pdu",
      assetIdSha256: hash("8"),
      independentlyControlled: true,
    },
    observer: {
      id: "lab-observer",
      organization: "independent-lab",
    },
    cutPoints: [...POWER_LOSS_CUT_POINTS],
    repetitionsPerCut: 10,
    runs,
    summary: {
      actualPhysicalCuts: 100,
      everyRebootCompleted: true,
      partialPublications: 0,
      sqliteIntegrityFailures: 0,
      rollbackViolations: 0,
      recoverySynthesisViolations: 0,
      unexplainedManagedObjects: 0,
    },
    review: {
      reviewer: "release-reviewer",
      reviewedAt: "2026-09-01T01:00:00Z",
      evidenceAccepted: true,
    },
  };
}

test("accepts only a complete independently reviewed 100-cut ledger", () => {
  const result = validatePhysicalPowerLossLedger(ledger());
  assert.equal(result.physicalCuts, 100);
  assert.equal(result.eligibleForGateReview, true);
});

test("rejects incomplete, duplicate, non-physical, and failed rows", () => {
  const cases = [
    (value) => value.runs.pop(),
    (value) => {
      value.runs[1].cutPoint = value.runs[0].cutPoint;
      value.runs[1].repetition = value.runs[0].repetition;
    },
    (value) => {
      value.powerController.kind = "process";
    },
    (value) => {
      value.runs[0].sqlite.state.integrityCheck = "corrupt";
    },
    (value) => {
      value.runs[0].partialPublicationAccepted = true;
    },
    (value) => {
      value.review.reviewer = value.observer.id;
    },
  ];
  for (const mutate of cases) {
    const value = ledger();
    mutate(value);
    assert.throws(
      () => validatePhysicalPowerLossLedger(value),
      PowerLossLedgerError,
    );
  }
});

test("strict parsing rejects duplicate JSON keys", () => {
  assert.throws(
    () =>
      parseAndValidatePhysicalPowerLossLedger(
        '{"schemaVersion":2,"schemaVersion":2}',
      ),
    PowerLossLedgerError,
  );
});
