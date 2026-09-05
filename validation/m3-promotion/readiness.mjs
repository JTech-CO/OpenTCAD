import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
  realpathSync,
  statSync,
} from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";

export const M3_GATE_IDS = Object.freeze([
  "runtime-adapters",
  "native-fencing",
  "local-transport",
  "lifecycle-integration",
  "credentials-and-scheduler",
  "power-loss",
  "platform-qualification",
  "solver-release",
]);

export const M3_REQUIRED_QUALIFICATIONS = Object.freeze(
  ["windows", "macos", "linux"].flatMap((platform) =>
    ["docker", "podman"].map((backend) => `${platform}/${backend}`),
  ),
);

export const PromotionErrorCode = Object.freeze({
  INPUT_INVALID: "promotion-input-invalid",
  REVISION_MISMATCH: "promotion-revision-mismatch",
  WORKTREE_DIRTY: "promotion-worktree-dirty",
  PARTIAL_APPROVAL: "promotion-partial-approval",
  EVIDENCE_DRIFT: "promotion-evidence-drift",
  QUALIFICATION_INCOMPLETE: "promotion-runtime-qualification-incomplete",
  RUNTIME_BINDING_MISMATCH: "promotion-runtime-binding-mismatch",
  IMAGE_BINDING_MISMATCH: "promotion-image-binding-mismatch",
});

export class PromotionReadinessError extends Error {
  constructor(code) {
    if (!Object.values(PromotionErrorCode).includes(code)) {
      throw new TypeError("PromotionReadinessError requires a stable code.");
    }
    super(code);
    this.name = "PromotionReadinessError";
    this.code = code;
  }

  asObject() {
    return { code: this.code };
  }
}

const SHA256 = /^[0-9a-f]{64}$/u;
const DIGEST = /^sha256:[0-9a-f]{64}$/u;
const REVISION = /^[0-9a-f]{40}$/u;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const ENTRYPOINT = /^[a-z][a-z0-9-]{0,62}$/u;
const IMAGE_ID = ENTRYPOINT;
const APPROVAL_TIME = /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/u;
const PLATFORMS = new Set(["windows", "macos", "linux"]);
const BACKENDS = new Set(["docker", "podman"]);
const ARCHITECTURES = new Set(["amd64", "arm64"]);
const MAX_JSON_BYTES = 16 * 1024 * 1024;
const MAX_EVIDENCE_BYTES = 256 * 1024 * 1024;

function fail(code) {
  throw new PromotionReadinessError(code);
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value, keys, code = PromotionErrorCode.INPUT_INVALID) {
  if (!isRecord(value)) {
    fail(code);
  }
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    fail(code);
  }
  return value;
}

function requireText(value, maximum = 256) {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) {
    fail(PromotionErrorCode.INPUT_INVALID);
  }
  return value;
}

function requireMatch(value, pattern, code = PromotionErrorCode.INPUT_INVALID) {
  if (typeof value !== "string" || !pattern.test(value)) {
    fail(code);
  }
  return value;
}

function requireApprovalTime(value) {
  requireMatch(value, APPROVAL_TIME);
  const milliseconds = Date.parse(value);
  if (
    !Number.isFinite(milliseconds) ||
    new Date(milliseconds).toISOString().replace(".000Z", "Z") !== value
  ) {
    fail(PromotionErrorCode.INPUT_INVALID);
  }
  return value;
}

function requireRelativePath(value) {
  requireText(value, 512);
  if (
    value.startsWith("/") ||
    value.startsWith("\\") ||
    value.includes("\\") ||
    value.includes(":") ||
    value.split("/").some((part) => part === "" || part === "." || part === "..")
  ) {
    fail(PromotionErrorCode.INPUT_INVALID);
  }
  return value;
}

function strictJsonParser(source) {
  let offset = 0;

  function whitespace() {
    while (offset < source.length && /[\u0009\u000a\u000d\u0020]/u.test(source[offset])) {
      offset += 1;
    }
  }

  function stringValue() {
    const start = offset;
    offset += 1;
    let escaped = false;
    while (offset < source.length) {
      const character = source[offset];
      if (escaped) {
        escaped = false;
        offset += 1;
        continue;
      }
      if (character === "\\") {
        escaped = true;
        offset += 1;
        continue;
      }
      if (character === '"') {
        offset += 1;
        try {
          return JSON.parse(source.slice(start, offset));
        } catch {
          fail(PromotionErrorCode.INPUT_INVALID);
        }
      }
      if (character.charCodeAt(0) < 0x20) {
        fail(PromotionErrorCode.INPUT_INVALID);
      }
      offset += 1;
    }
    fail(PromotionErrorCode.INPUT_INVALID);
  }

  function arrayValue() {
    const result = [];
    offset += 1;
    whitespace();
    if (source[offset] === "]") {
      offset += 1;
      return result;
    }
    while (offset < source.length) {
      result.push(value());
      whitespace();
      if (source[offset] === "]") {
        offset += 1;
        return result;
      }
      if (source[offset] !== ",") {
        fail(PromotionErrorCode.INPUT_INVALID);
      }
      offset += 1;
      whitespace();
    }
    fail(PromotionErrorCode.INPUT_INVALID);
  }

  function objectValue() {
    const result = {};
    const keys = new Set();
    offset += 1;
    whitespace();
    if (source[offset] === "}") {
      offset += 1;
      return result;
    }
    while (offset < source.length) {
      if (source[offset] !== '"') {
        fail(PromotionErrorCode.INPUT_INVALID);
      }
      const key = stringValue();
      if (keys.has(key)) {
        fail(PromotionErrorCode.INPUT_INVALID);
      }
      keys.add(key);
      whitespace();
      if (source[offset] !== ":") {
        fail(PromotionErrorCode.INPUT_INVALID);
      }
      offset += 1;
      result[key] = value();
      whitespace();
      if (source[offset] === "}") {
        offset += 1;
        return result;
      }
      if (source[offset] !== ",") {
        fail(PromotionErrorCode.INPUT_INVALID);
      }
      offset += 1;
      whitespace();
    }
    fail(PromotionErrorCode.INPUT_INVALID);
  }

  function numberValue() {
    const match = source.slice(offset).match(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/u);
    if (!match) {
      fail(PromotionErrorCode.INPUT_INVALID);
    }
    offset += match[0].length;
    const parsed = Number(match[0]);
    if (!Number.isFinite(parsed)) {
      fail(PromotionErrorCode.INPUT_INVALID);
    }
    return parsed;
  }

  function literal(text, parsed) {
    if (source.slice(offset, offset + text.length) !== text) {
      fail(PromotionErrorCode.INPUT_INVALID);
    }
    offset += text.length;
    return parsed;
  }

  function value() {
    whitespace();
    const character = source[offset];
    if (character === "{") return objectValue();
    if (character === "[") return arrayValue();
    if (character === '"') return stringValue();
    if (character === "t") return literal("true", true);
    if (character === "f") return literal("false", false);
    if (character === "n") return literal("null", null);
    return numberValue();
  }

  const result = value();
  whitespace();
  if (offset !== source.length) {
    fail(PromotionErrorCode.INPUT_INVALID);
  }
  return result;
}

export function parseStrictJson(source) {
  if (typeof source !== "string" || source.length === 0) {
    fail(PromotionErrorCode.INPUT_INVALID);
  }
  return strictJsonParser(source);
}

export function sha256Hex(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function readBoundedFile(root, path, maximum = MAX_EVIDENCE_BYTES) {
  requireRelativePath(path);
  try {
    const realRoot = realpathSync(root);
    const unresolved = resolve(realRoot, path);
    const linkStatus = lstatSync(unresolved);
    if (linkStatus.isSymbolicLink() || !linkStatus.isFile()) {
      fail(PromotionErrorCode.EVIDENCE_DRIFT);
    }
    const target = realpathSync(unresolved);
    const fromRoot = relative(realRoot, target);
    if (fromRoot === "" || fromRoot.startsWith("..") || isAbsolute(fromRoot)) {
      fail(PromotionErrorCode.EVIDENCE_DRIFT);
    }
    const status = statSync(target);
    if (!status.isFile() || status.size < 1 || status.size > maximum) {
      fail(PromotionErrorCode.EVIDENCE_DRIFT);
    }
    return readFileSync(target);
  } catch (error) {
    if (error instanceof PromotionReadinessError) {
      throw error;
    }
    fail(PromotionErrorCode.EVIDENCE_DRIFT);
  }
}

function readJson(root, path) {
  const bytes = readBoundedFile(root, path, MAX_JSON_BYTES);
  let source;
  try {
    source = bytes.toString("utf8");
    if (Buffer.from(source, "utf8").compare(bytes) !== 0) {
      fail(PromotionErrorCode.INPUT_INVALID);
    }
  } catch {
    fail(PromotionErrorCode.INPUT_INVALID);
  }
  return { bytes, value: parseStrictJson(source) };
}

function hashReference(value) {
  const record = exactKeys(value, ["path", "sha256"]);
  return {
    path: requireRelativePath(record.path),
    sha256: requireMatch(record.sha256, SHA256),
  };
}

function revisionEvidence(value, revision) {
  const record = exactKeys(value, ["path", "sha256", "revision"]);
  const result = {
    path: requireRelativePath(record.path),
    sha256: requireMatch(record.sha256, SHA256),
    revision: requireMatch(record.revision, REVISION),
  };
  if (result.revision !== revision) {
    fail(PromotionErrorCode.REVISION_MISMATCH);
  }
  return result;
}

function verifyReference(root, reference) {
  const bytes = readBoundedFile(root, reference.path);
  if (sha256Hex(bytes) !== reference.sha256) {
    fail(PromotionErrorCode.EVIDENCE_DRIFT);
  }
  return bytes;
}

function readJsonReference(root, reference) {
  const result = readJson(root, reference.path);
  if (sha256Hex(result.bytes) !== reference.sha256) {
    fail(PromotionErrorCode.EVIDENCE_DRIFT);
  }
  return result.value;
}

function imageIdentity(value, style = "camel") {
  const keys =
    style === "snake"
      ? ["reference", "index_digest", "platform_manifest_digest", "platform"]
      : ["reference", "indexDigest", "platformManifestDigest", "platform"];
  const record = exactKeys(value, keys);
  const indexDigest = requireMatch(
    record[style === "snake" ? "index_digest" : "indexDigest"],
    DIGEST,
  );
  const platformManifestDigest = requireMatch(
    record[style === "snake" ? "platform_manifest_digest" : "platformManifestDigest"],
    DIGEST,
  );
  const reference = requireText(record.reference, 512);
  if (!reference.endsWith(`@${indexDigest}`)) {
    fail(PromotionErrorCode.IMAGE_BINDING_MISMATCH);
  }
  if (!["linux/amd64", "linux/arm64"].includes(record.platform)) {
    fail(PromotionErrorCode.IMAGE_BINDING_MISMATCH);
  }
  return {
    reference,
    indexDigest,
    platformManifestDigest,
    platform: record.platform,
  };
}

function identityKey(identity) {
  return JSON.stringify([
    identity.reference,
    identity.indexDigest,
    identity.platformManifestDigest,
    identity.platform,
  ]);
}

function referenceKey(reference) {
  return JSON.stringify([reference.path, reference.sha256]);
}

function validateManifest(value) {
  const manifest = exactKeys(value, [
    "schemaVersion",
    "productEnabled",
    "approvalId",
    "approvedBy",
    "approvedAt",
    "gates",
    "runtime",
  ]);
  if (manifest.schemaVersion !== 1 || manifest.productEnabled !== true) {
    fail(PromotionErrorCode.PARTIAL_APPROVAL);
  }
  const approval = {
    approvalId: requireMatch(manifest.approvalId, UUID),
    approvedBy: requireText(manifest.approvedBy),
    approvedAt: requireApprovalTime(manifest.approvedAt),
  };
  if (!Array.isArray(manifest.gates) || manifest.gates.length !== M3_GATE_IDS.length) {
    fail(PromotionErrorCode.PARTIAL_APPROVAL);
  }
  const gates = manifest.gates.map((value, index) => {
    const gate = exactKeys(
      value,
      ["id", "approved", "approvedBy", "approvedAt", "evidence"],
      PromotionErrorCode.PARTIAL_APPROVAL,
    );
    if (gate.id !== M3_GATE_IDS[index] || gate.approved !== true) {
      fail(PromotionErrorCode.PARTIAL_APPROVAL);
    }
    if (!Array.isArray(gate.evidence) || gate.evidence.length < 1) {
      fail(PromotionErrorCode.PARTIAL_APPROVAL);
    }
    const evidence = gate.evidence.map(hashReference);
    if (new Set(evidence.map(referenceKey)).size !== evidence.length) {
      fail(PromotionErrorCode.INPUT_INVALID);
    }
    return {
      id: gate.id,
      approved: true,
      approvedBy: requireText(gate.approvedBy),
      approvedAt: requireApprovalTime(gate.approvedAt),
      evidence,
    };
  });

  const runtime = exactKeys(manifest.runtime, ["grants"]);
  if (!Array.isArray(runtime.grants) || runtime.grants.length < 1) {
    fail(PromotionErrorCode.PARTIAL_APPROVAL);
  }
  const grants = runtime.grants.map((value) => {
    const grant = exactKeys(value, ["backend", "image", "entrypoint"]);
    if (!BACKENDS.has(grant.backend)) {
      fail(PromotionErrorCode.RUNTIME_BINDING_MISMATCH);
    }
    return {
      backend: grant.backend,
      image: imageIdentity(grant.image, "snake"),
      entrypoint: requireMatch(grant.entrypoint, ENTRYPOINT),
    };
  });
  const grantKeys = grants.map(
    (grant) => `${grant.backend}|${identityKey(grant.image)}|${grant.entrypoint}`,
  );
  if (
    new Set(grantKeys).size !== grantKeys.length ||
    new Set(grants.map(({ backend }) => backend)).size !== BACKENDS.size
  ) {
    fail(PromotionErrorCode.RUNTIME_BINDING_MISMATCH);
  }
  return { approval, gates, grants };
}

function validateReadiness(value, expectedRevision) {
  const readiness = exactKeys(value, [
    "schemaVersion",
    "evidenceType",
    "revision",
    "manifest",
    "imageLock",
    "approval",
    "gates",
    "runtimeQualifications",
  ]);
  if (
    readiness.schemaVersion !== 1 ||
    readiness.evidenceType !== "m3-promotion-readiness"
  ) {
    fail(PromotionErrorCode.INPUT_INVALID);
  }
  const revision = requireMatch(readiness.revision, REVISION);
  if (revision !== expectedRevision) {
    fail(PromotionErrorCode.REVISION_MISMATCH);
  }
  const approvalValue = exactKeys(readiness.approval, [
    "approvalId",
    "approvedBy",
    "approvedAt",
  ]);
  const approval = {
    approvalId: requireMatch(approvalValue.approvalId, UUID),
    approvedBy: requireText(approvalValue.approvedBy),
    approvedAt: requireApprovalTime(approvalValue.approvedAt),
  };
  if (!Array.isArray(readiness.gates) || readiness.gates.length !== M3_GATE_IDS.length) {
    fail(PromotionErrorCode.PARTIAL_APPROVAL);
  }
  const gates = readiness.gates.map((value, index) => {
    const gate = exactKeys(
      value,
      ["id", "approved", "approvedBy", "approvedAt", "evidence"],
      PromotionErrorCode.PARTIAL_APPROVAL,
    );
    if (gate.id !== M3_GATE_IDS[index] || gate.approved !== true) {
      fail(PromotionErrorCode.PARTIAL_APPROVAL);
    }
    if (!Array.isArray(gate.evidence) || gate.evidence.length < 1) {
      fail(PromotionErrorCode.PARTIAL_APPROVAL);
    }
    const evidence = gate.evidence.map((item) => revisionEvidence(item, revision));
    return {
      id: gate.id,
      approved: true,
      approvedBy: requireText(gate.approvedBy),
      approvedAt: requireApprovalTime(gate.approvedAt),
      evidence,
    };
  });
  if (
    !Array.isArray(readiness.runtimeQualifications) ||
    readiness.runtimeQualifications.length !== M3_REQUIRED_QUALIFICATIONS.length
  ) {
    fail(PromotionErrorCode.QUALIFICATION_INCOMPLETE);
  }
  const qualifications = readiness.runtimeQualifications.map((value) => {
    const item = exactKeys(value, ["platform", "backend", "evidence"]);
    if (!PLATFORMS.has(item.platform) || !BACKENDS.has(item.backend)) {
      fail(PromotionErrorCode.QUALIFICATION_INCOMPLETE);
    }
    return {
      platform: item.platform,
      backend: item.backend,
      evidence: revisionEvidence(item.evidence, revision),
    };
  });
  const combinations = qualifications.map(({ platform, backend }) => `${platform}/${backend}`);
  if (
    new Set(combinations).size !== M3_REQUIRED_QUALIFICATIONS.length ||
    M3_REQUIRED_QUALIFICATIONS.some((combination) => !combinations.includes(combination))
  ) {
    fail(PromotionErrorCode.QUALIFICATION_INCOMPLETE);
  }
  return {
    revision,
    manifest: hashReference(readiness.manifest),
    imageLock: hashReference(readiness.imageLock),
    approval,
    gates,
    qualifications,
  };
}

function validateImageLock(root, value, revision) {
  const lock = exactKeys(value, ["schemaVersion", "evidenceType", "revision", "images"]);
  if (
    lock.schemaVersion !== 2 ||
    lock.evidenceType !== "m3-release-image-lock" ||
    requireMatch(lock.revision, REVISION) !== revision ||
    !Array.isArray(lock.images) ||
    lock.images.length < 1
  ) {
    fail(PromotionErrorCode.IMAGE_BINDING_MISMATCH);
  }
  const images = lock.images.map((value) => {
    const image = exactKeys(
      value,
      ["id", "identity", "sbom", "licenseEvidence", "releaseApproved"],
      PromotionErrorCode.IMAGE_BINDING_MISMATCH,
    );
    if (image.releaseApproved !== true) {
      fail(PromotionErrorCode.IMAGE_BINDING_MISMATCH);
    }
    const result = {
      id: requireMatch(image.id, IMAGE_ID),
      identity: imageIdentity(image.identity),
      sbom: hashReference(image.sbom),
      licenseEvidence: hashReference(image.licenseEvidence),
    };
    verifyReference(root, result.sbom);
    verifyReference(root, result.licenseEvidence);
    return result;
  });
  if (
    new Set(images.map(({ id }) => id)).size !== images.length ||
    new Set(images.map(({ identity }) => identityKey(identity))).size !== images.length
  ) {
    fail(PromotionErrorCode.IMAGE_BINDING_MISMATCH);
  }
  return images;
}

function validateQualification(root, item, revision, grants, lockedImages) {
  const evidence = readJsonReference(root, item.evidence);
  const record = exactKeys(
    evidence,
    [
      "schemaVersion",
      "evidenceType",
      "evidenceId",
      "revision",
      "platform",
      "backend",
      "observedAt",
      "reviewer",
      "reviewedAt",
      "runtime",
      "contractSuitePassed",
      "nativeConformancePassed",
      "images",
    ],
    PromotionErrorCode.QUALIFICATION_INCOMPLETE,
  );
  if (
    record.schemaVersion !== 1 ||
    record.evidenceType !== "m3-native-runtime-qualification" ||
    requireMatch(record.evidenceId, UUID) === "" ||
    requireMatch(record.revision, REVISION) !== revision ||
    record.platform !== item.platform ||
    record.backend !== item.backend ||
    record.contractSuitePassed !== true ||
    record.nativeConformancePassed !== true
  ) {
    fail(PromotionErrorCode.QUALIFICATION_INCOMPLETE);
  }
  const observedAt = requireApprovalTime(record.observedAt);
  requireText(record.reviewer);
  const reviewedAt = requireApprovalTime(record.reviewedAt);
  if (Date.parse(reviewedAt) < Date.parse(observedAt)) {
    fail(PromotionErrorCode.QUALIFICATION_INCOMPLETE);
  }
  const runtime = exactKeys(
    record.runtime,
    [
      "clientVersion",
      "serverVersion",
      "serverOs",
      "serverArchitecture",
      "executableSha256",
    ],
    PromotionErrorCode.RUNTIME_BINDING_MISMATCH,
  );
  requireText(runtime.clientVersion, 128);
  requireText(runtime.serverVersion, 128);
  if (
    runtime.serverOs !== "linux" ||
    !ARCHITECTURES.has(runtime.serverArchitecture) ||
    !SHA256.test(runtime.executableSha256)
  ) {
    fail(PromotionErrorCode.RUNTIME_BINDING_MISMATCH);
  }
  if (!Array.isArray(record.images) || record.images.length < 1) {
    fail(PromotionErrorCode.RUNTIME_BINDING_MISMATCH);
  }

  const lockedByIdentity = new Map(
    lockedImages.map((image) => [identityKey(image.identity), image]),
  );
  const actual = new Map();
  for (const value of record.images) {
    const image = exactKeys(
      value,
      ["identity", "sbom", "entrypoints"],
      PromotionErrorCode.RUNTIME_BINDING_MISMATCH,
    );
    const identity = imageIdentity(image.identity);
    const key = identityKey(identity);
    const sbom = hashReference(image.sbom);
    if (
      identity.platform !== `linux/${runtime.serverArchitecture}` ||
      actual.has(key) ||
      !Array.isArray(image.entrypoints) ||
      image.entrypoints.length < 1
    ) {
      fail(PromotionErrorCode.RUNTIME_BINDING_MISMATCH);
    }
    const entrypoints = image.entrypoints.map((entrypoint) =>
      requireMatch(entrypoint, ENTRYPOINT),
    );
    if (new Set(entrypoints).size !== entrypoints.length) {
      fail(PromotionErrorCode.RUNTIME_BINDING_MISMATCH);
    }
    const locked = lockedByIdentity.get(key);
    if (!locked || referenceKey(locked.sbom) !== referenceKey(sbom)) {
      fail(PromotionErrorCode.IMAGE_BINDING_MISMATCH);
    }
    verifyReference(root, sbom);
    actual.set(key, [...entrypoints].sort());
  }

  const expected = new Map();
  for (const grant of grants) {
    if (
      grant.backend !== item.backend ||
      grant.image.platform !== `linux/${runtime.serverArchitecture}`
    ) {
      continue;
    }
    const key = identityKey(grant.image);
    const entrypoints = expected.get(key) ?? [];
    entrypoints.push(grant.entrypoint);
    expected.set(key, entrypoints);
  }
  if (expected.size < 1 || expected.size !== actual.size) {
    fail(PromotionErrorCode.RUNTIME_BINDING_MISMATCH);
  }
  for (const [key, entrypoints] of expected) {
    const observed = actual.get(key);
    if (
      !observed ||
      JSON.stringify([...entrypoints].sort()) !== JSON.stringify(observed)
    ) {
      fail(PromotionErrorCode.RUNTIME_BINDING_MISMATCH);
    }
  }
}

function sameApproval(left, right) {
  return (
    left.approvalId === right.approvalId &&
    left.approvedBy === right.approvedBy &&
    left.approvedAt === right.approvedAt
  );
}

function sameGate(left, right) {
  return (
    left.id === right.id &&
    left.approvedBy === right.approvedBy &&
    left.approvedAt === right.approvedAt &&
    JSON.stringify(left.evidence.map(referenceKey)) ===
      JSON.stringify(right.evidence.map(referenceKey))
  );
}

export function validateM3Promotion({
  repositoryRoot,
  manifestPath,
  readinessPath,
  expectedRevision,
}) {
  const root = realpathSync(repositoryRoot);
  const manifestRelative = requireRelativePath(manifestPath);
  const readinessRelative = requireRelativePath(readinessPath);
  const revision = requireMatch(expectedRevision, REVISION);

  const readinessDocument = readJson(root, readinessRelative).value;
  const readiness = validateReadiness(readinessDocument, revision);
  if (readiness.manifest.path !== manifestRelative) {
    fail(PromotionErrorCode.EVIDENCE_DRIFT);
  }
  const manifestDocument = readJsonReference(root, readiness.manifest);
  const manifest = validateManifest(manifestDocument);
  if (!sameApproval(manifest.approval, readiness.approval)) {
    fail(PromotionErrorCode.PARTIAL_APPROVAL);
  }
  for (let index = 0; index < M3_GATE_IDS.length; index += 1) {
    if (!sameGate(manifest.gates[index], readiness.gates[index])) {
      fail(PromotionErrorCode.PARTIAL_APPROVAL);
    }
    for (const evidence of readiness.gates[index].evidence) {
      verifyReference(root, evidence);
    }
  }

  const imageLockDocument = readJsonReference(root, readiness.imageLock);
  const lockedImages = validateImageLock(root, imageLockDocument, revision);
  const grantedImageKeys = new Set(manifest.grants.map(({ image }) => identityKey(image)));
  const lockedImageKeys = new Set(lockedImages.map(({ identity }) => identityKey(identity)));
  if (
    grantedImageKeys.size !== lockedImageKeys.size ||
    [...grantedImageKeys].some((key) => !lockedImageKeys.has(key))
  ) {
    fail(PromotionErrorCode.IMAGE_BINDING_MISMATCH);
  }

  for (const qualification of readiness.qualifications) {
    validateQualification(
      root,
      qualification,
      revision,
      manifest.grants,
      lockedImages,
    );
  }

  return Object.freeze({
    status: "ready",
    revision,
    manifestSha256: readiness.manifest.sha256,
    approvalId: manifest.approval.approvalId,
    approvedGateCount: manifest.gates.length,
    qualificationCount: readiness.qualifications.length,
    runtimeGrantCount: manifest.grants.length,
    imageCount: lockedImages.length,
  });
}
