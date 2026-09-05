import { parseStrictJson } from "../m3-promotion/readiness.mjs";

export const POWER_LOSS_CUT_POINTS = Object.freeze([
  "control-commit",
  "state-backup",
  "authority-backup",
  "authentication-record",
  "export-publication",
  "restore-floor-commit",
  "state-restore",
  "authority-restore",
  "import-record",
  "import-publication",
]);

export const PowerLossLedgerErrorCode = Object.freeze({
  INPUT_INVALID: "power-loss-ledger-invalid",
  MATRIX_INCOMPLETE: "power-loss-matrix-incomplete",
  NON_PHYSICAL: "power-loss-not-physical",
  INTEGRITY_FAILED: "power-loss-integrity-failed",
  REVIEW_INVALID: "power-loss-review-invalid",
});

export class PowerLossLedgerError extends Error {
  constructor(code) {
    if (!Object.values(PowerLossLedgerErrorCode).includes(code)) {
      throw new TypeError("PowerLossLedgerError requires a stable code.");
    }
    super(code);
    this.name = "PowerLossLedgerError";
    this.code = code;
  }
}

const SHA256 = /^[0-9a-f]{64}$/u;
const REVISION = /^[0-9a-f]{40}$/u;
const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const UTC_SECONDS =
  /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/u;
const PLATFORMS = new Set(["windows", "macos", "linux"]);
const ARCHITECTURES = new Set(["amd64", "arm64"]);
const PHYSICAL_CONTROLLERS = new Set(["pdu", "relay", "battery-cut"]);

function fail(code = PowerLossLedgerErrorCode.INPUT_INVALID) {
  throw new PowerLossLedgerError(code);
}

function record(value, keys, code = PowerLossLedgerErrorCode.INPUT_INVALID) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail(code);
  }
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    fail(code);
  }
  return value;
}

function text(value, maximum = 256) {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) {
    fail();
  }
  return value;
}

function match(value, pattern, code = PowerLossLedgerErrorCode.INPUT_INVALID) {
  if (typeof value !== "string" || !pattern.test(value)) {
    fail(code);
  }
  return value;
}

function utc(value) {
  match(value, UTC_SECONDS);
  if (!Number.isFinite(Date.parse(value))) {
    fail();
  }
  return value;
}

function positiveInteger(value, minimum, maximum) {
  if (
    !Number.isInteger(value) ||
    value < minimum ||
    value > maximum
  ) {
    fail();
  }
  return value;
}

function integrityRecord(value) {
  const result = record(
    value,
    ["quickCheck", "integrityCheck"],
    PowerLossLedgerErrorCode.INTEGRITY_FAILED,
  );
  if (result.quickCheck !== "ok" || result.integrityCheck !== "ok") {
    fail(PowerLossLedgerErrorCode.INTEGRITY_FAILED);
  }
}

function validateRun(value, repetitionsPerCut) {
  const run = record(value, [
    "runId",
    "cutPoint",
    "repetition",
    "abruptPowerCut",
    "armedAt",
    "rebootObservedAt",
    "preCutBootId",
    "postCutBootId",
    "preCutMarkerSha256",
    "hostLogSha256",
    "observerRecordSha256",
    "sqlite",
    "partialPublicationAccepted",
    "rollbackViolation",
    "recoverySynthesizedSuccess",
    "unexplainedManagedObjects",
  ]);
  match(run.runId, UUID);
  if (!POWER_LOSS_CUT_POINTS.includes(run.cutPoint)) {
    fail();
  }
  positiveInteger(run.repetition, 1, repetitionsPerCut);
  if (run.abruptPowerCut !== true) {
    fail(PowerLossLedgerErrorCode.NON_PHYSICAL);
  }
  const armed = Date.parse(utc(run.armedAt));
  const rebooted = Date.parse(utc(run.rebootObservedAt));
  if (rebooted <= armed) {
    fail();
  }
  text(run.preCutBootId, 256);
  text(run.postCutBootId, 256);
  if (run.preCutBootId === run.postCutBootId) {
    fail(PowerLossLedgerErrorCode.NON_PHYSICAL);
  }
  for (const hash of (
    [
      run.preCutMarkerSha256,
      run.hostLogSha256,
      run.observerRecordSha256,
    ]
  )) {
    match(hash, SHA256);
  }
  const sqlite = record(
    run.sqlite,
    ["control", "state", "fence"],
    PowerLossLedgerErrorCode.INTEGRITY_FAILED,
  );
  integrityRecord(sqlite.control);
  integrityRecord(sqlite.state);
  integrityRecord(sqlite.fence);
  if (
    run.partialPublicationAccepted !== false ||
    run.rollbackViolation !== false ||
    run.recoverySynthesizedSuccess !== false ||
    run.unexplainedManagedObjects !== 0
  ) {
    fail(PowerLossLedgerErrorCode.INTEGRITY_FAILED);
  }
  return run;
}

export function validatePhysicalPowerLossLedger(value) {
  const ledger = record(value, [
    "schemaVersion",
    "evidenceId",
    "revision",
    "activationManifestSha256",
    "runtimeGrantsSha256",
    "imageLockSha256",
    "platform",
    "architecture",
    "osVersion",
    "filesystem",
    "storage",
    "powerController",
    "observer",
    "cutPoints",
    "repetitionsPerCut",
    "runs",
    "summary",
    "review",
  ]);
  if (ledger.schemaVersion !== 2) {
    fail();
  }
  match(ledger.evidenceId, UUID);
  match(ledger.revision, REVISION);
  match(ledger.activationManifestSha256, SHA256);
  match(ledger.runtimeGrantsSha256, SHA256);
  match(ledger.imageLockSha256, SHA256);
  if (
    !PLATFORMS.has(ledger.platform) ||
    !ARCHITECTURES.has(ledger.architecture)
  ) {
    fail();
  }
  text(ledger.osVersion);
  text(ledger.filesystem, 128);

  const storage = record(ledger.storage, [
    "model",
    "firmware",
    "serialSha256",
    "controller",
    "writeCacheConfiguration",
  ]);
  text(storage.model);
  text(storage.firmware);
  match(storage.serialSha256, SHA256);
  text(storage.controller);
  text(storage.writeCacheConfiguration, 512);

  const controller = record(ledger.powerController, [
    "kind",
    "model",
    "assetIdSha256",
    "independentlyControlled",
  ]);
  if (
    !PHYSICAL_CONTROLLERS.has(controller.kind) ||
    controller.independentlyControlled !== true
  ) {
    fail(PowerLossLedgerErrorCode.NON_PHYSICAL);
  }
  text(controller.model);
  match(controller.assetIdSha256, SHA256);

  const observer = record(ledger.observer, ["id", "organization"]);
  text(observer.id, 128);
  text(observer.organization, 256);

  if (
    !Array.isArray(ledger.cutPoints) ||
    JSON.stringify(ledger.cutPoints) !== JSON.stringify(POWER_LOSS_CUT_POINTS)
  ) {
    fail(PowerLossLedgerErrorCode.MATRIX_INCOMPLETE);
  }
  const repetitions = positiveInteger(ledger.repetitionsPerCut, 10, 100);
  const expectedRuns = POWER_LOSS_CUT_POINTS.length * repetitions;
  if (!Array.isArray(ledger.runs) || ledger.runs.length !== expectedRuns) {
    fail(PowerLossLedgerErrorCode.MATRIX_INCOMPLETE);
  }
  const runIds = new Set();
  const cells = new Set();
  const postCutBootIds = new Set();
  for (const candidate of ledger.runs) {
    const run = validateRun(candidate, repetitions);
    const cell = `${run.cutPoint}/${run.repetition}`;
    if (
      runIds.has(run.runId) ||
      cells.has(cell) ||
      postCutBootIds.has(run.postCutBootId)
    ) {
      fail(PowerLossLedgerErrorCode.MATRIX_INCOMPLETE);
    }
    runIds.add(run.runId);
    cells.add(cell);
    postCutBootIds.add(run.postCutBootId);
  }
  for (const cutPoint of POWER_LOSS_CUT_POINTS) {
    for (let repetition = 1; repetition <= repetitions; repetition += 1) {
      if (!cells.has(`${cutPoint}/${repetition}`)) {
        fail(PowerLossLedgerErrorCode.MATRIX_INCOMPLETE);
      }
    }
  }

  const summary = record(ledger.summary, [
    "actualPhysicalCuts",
    "everyRebootCompleted",
    "partialPublications",
    "sqliteIntegrityFailures",
    "rollbackViolations",
    "recoverySynthesisViolations",
    "unexplainedManagedObjects",
  ]);
  if (
    summary.actualPhysicalCuts !== expectedRuns ||
    summary.everyRebootCompleted !== true ||
    summary.partialPublications !== 0 ||
    summary.sqliteIntegrityFailures !== 0 ||
    summary.rollbackViolations !== 0 ||
    summary.recoverySynthesisViolations !== 0 ||
    summary.unexplainedManagedObjects !== 0
  ) {
    fail(PowerLossLedgerErrorCode.INTEGRITY_FAILED);
  }

  const review = record(ledger.review, [
    "reviewer",
    "reviewedAt",
    "evidenceAccepted",
  ]);
  text(review.reviewer, 128);
  utc(review.reviewedAt);
  if (
    review.evidenceAccepted !== true ||
    review.reviewer === observer.id
  ) {
    fail(PowerLossLedgerErrorCode.REVIEW_INVALID);
  }
  return Object.freeze({
    evidenceId: ledger.evidenceId,
    revision: ledger.revision,
    platform: ledger.platform,
    architecture: ledger.architecture,
    physicalCuts: expectedRuns,
    eligibleForGateReview: true,
  });
}

export function parseAndValidatePhysicalPowerLossLedger(source) {
  try {
    return validatePhysicalPowerLossLedger(parseStrictJson(source));
  } catch (error) {
    if (error instanceof PowerLossLedgerError) {
      throw error;
    }
    fail(PowerLossLedgerErrorCode.INPUT_INVALID);
  }
}
