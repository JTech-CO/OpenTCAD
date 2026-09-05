import { createHash } from "node:crypto";
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const DIGEST = /^sha256:([0-9a-f]{64})$/;
const SHA256 = /^[0-9a-f]{64}$/;
const COMMIT = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;
const PLACEHOLDER = /\b(?:pending|placeholder|todo|tbd|unknown|unresolved|not[- ]provided)\b|\.invalid(?:[\/:]|$)/i;
const REVIEW_PLACEHOLDER = /\b(?:contract|fixture|example|sample|test)\b/i;
const IMAGE_ROLES = ["transfer", "suprem", "devsim", "gmsh"];
const RELEASE_PLATFORMS = ["linux/amd64", "linux/arm64"];
const CORPUS_ENGINES = ["SUPREM-IV.GS", "DEVSIM", "Gmsh"];
const CONTRACT_FIXTURE_ARTIFACT_PREFIX = "validation/solver-release/fixtures/";
const ENGINE_ROLE = new Map([
  ["SUPREM-IV.GS", "suprem"],
  ["DEVSIM", "devsim"],
  ["Gmsh", "gmsh"],
]);

export class SolverReleaseValidationError extends Error {
  constructor(message) {
    super(message);
    this.name = "SolverReleaseValidationError";
  }
}

function fail(message) {
  throw new SolverReleaseValidationError(message);
}

class StrictJsonParser {
  constructor(source, label) {
    this.source = source;
    this.label = label;
    this.offset = 0;
  }

  parse() {
    this.skipWhitespace();
    const value = this.parseValue("$");
    this.skipWhitespace();
    if (this.offset !== this.source.length) {
      this.error("unexpected trailing input");
    }
    return value;
  }

  error(message) {
    fail(`${this.label}: ${message} at byte ${Buffer.byteLength(this.source.slice(0, this.offset), "utf8")}`);
  }

  skipWhitespace() {
    while (/\s/.test(this.source[this.offset] ?? "") && " \t\r\n".includes(this.source[this.offset])) {
      this.offset += 1;
    }
  }

  parseValue(jsonPath) {
    const character = this.source[this.offset];
    if (character === "{") return this.parseObject(jsonPath);
    if (character === "[") return this.parseArray(jsonPath);
    if (character === '"') return this.parseString();
    if (character === "t") return this.parseLiteral("true", true);
    if (character === "f") return this.parseLiteral("false", false);
    if (character === "n") return this.parseLiteral("null", null);
    if (character === "-" || /[0-9]/.test(character ?? "")) return this.parseNumber();
    this.error("expected a JSON value");
  }

  parseObject(jsonPath) {
    const value = {};
    const keys = new Set();
    this.offset += 1;
    this.skipWhitespace();
    if (this.source[this.offset] === "}") {
      this.offset += 1;
      return value;
    }
    while (true) {
      if (this.source[this.offset] !== '"') this.error("expected an object key");
      const key = this.parseString();
      if (keys.has(key)) fail(`${this.label}: duplicate key ${JSON.stringify(key)} at ${jsonPath}`);
      keys.add(key);
      this.skipWhitespace();
      if (this.source[this.offset] !== ":") this.error("expected ':' after an object key");
      this.offset += 1;
      this.skipWhitespace();
      value[key] = this.parseValue(`${jsonPath}.${key}`);
      this.skipWhitespace();
      if (this.source[this.offset] === "}") {
        this.offset += 1;
        return value;
      }
      if (this.source[this.offset] !== ",") this.error("expected ',' or '}' in an object");
      this.offset += 1;
      this.skipWhitespace();
    }
  }

  parseArray(jsonPath) {
    const value = [];
    this.offset += 1;
    this.skipWhitespace();
    if (this.source[this.offset] === "]") {
      this.offset += 1;
      return value;
    }
    while (true) {
      value.push(this.parseValue(`${jsonPath}[${value.length}]`));
      this.skipWhitespace();
      if (this.source[this.offset] === "]") {
        this.offset += 1;
        return value;
      }
      if (this.source[this.offset] !== ",") this.error("expected ',' or ']' in an array");
      this.offset += 1;
      this.skipWhitespace();
    }
  }

  parseString() {
    const start = this.offset;
    this.offset += 1;
    let escaped = false;
    while (this.offset < this.source.length) {
      const character = this.source[this.offset];
      if (!escaped && character === '"') {
        this.offset += 1;
        try {
          return JSON.parse(this.source.slice(start, this.offset));
        } catch {
          this.error("invalid JSON string");
        }
      }
      if (!escaped && character.charCodeAt(0) < 0x20) this.error("unescaped control character in string");
      if (!escaped && character === "\\") {
        escaped = true;
      } else {
        escaped = false;
      }
      this.offset += 1;
    }
    this.error("unterminated JSON string");
  }

  parseLiteral(literal, value) {
    if (this.source.slice(this.offset, this.offset + literal.length) !== literal) {
      this.error(`invalid literal; expected ${literal}`);
    }
    this.offset += literal.length;
    return value;
  }

  parseNumber() {
    const remainder = this.source.slice(this.offset);
    const match = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(remainder);
    if (!match) this.error("invalid JSON number");
    this.offset += match[0].length;
    const value = Number(match[0]);
    if (!Number.isFinite(value)) this.error("non-finite JSON number");
    return value;
  }
}

export function parseStrictJson(source, label = "JSON") {
  if (typeof source !== "string") fail(`${label}: input must be text`);
  if (Buffer.byteLength(source, "utf8") > 4 * 1024 * 1024) fail(`${label}: input exceeds 4 MiB`);
  if (source.charCodeAt(0) === 0xfeff) fail(`${label}: UTF-8 BOM is not allowed`);
  return new StrictJsonParser(source, label).parse();
}

function exactObject(value, keys, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail(`${label} must be an object`);
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    fail(`${label} must contain exactly: ${expected.join(", ")}`);
  }
  return value;
}

function exactArray(value, label, minimum = 1) {
  if (!Array.isArray(value) || value.length < minimum) fail(`${label} must be an array with at least ${minimum} item(s)`);
  return value;
}

function text(value, label, context, { min = 1, max = 512, pattern } = {}) {
  if (typeof value !== "string" || value !== value.trim() || value.length < min || value.length > max) {
    fail(`${label} must be trimmed text between ${min} and ${max} characters`);
  }
  if (!context.allowContractFixture && PLACEHOLDER.test(value)) fail(`${label} contains placeholder text`);
  if (pattern && !pattern.test(value)) fail(`${label} has an invalid format`);
  return value;
}

function booleanTrue(value, label) {
  if (value !== true) fail(`${label} must be true`);
}

function integer(value, label, minimum) {
  if (!Number.isInteger(value) || value < minimum) fail(`${label} must be an integer greater than or equal to ${minimum}`);
  return value;
}

function digest(value, label) {
  text(value, label, { allowContractFixture: true }, { pattern: DIGEST });
  const hex = DIGEST.exec(value)[1];
  if (new Set(hex).size === 1) fail(`${label} must not be an all-repeated placeholder digest`);
  return value;
}

function sha256(value, label) {
  text(value, label, { allowContractFixture: true }, { pattern: SHA256 });
  if (new Set(value).size === 1) fail(`${label} must not be an all-repeated placeholder hash`);
  return value;
}

function commit(value, label) {
  text(value, label, { allowContractFixture: true }, { pattern: COMMIT });
  if (new Set(value).size === 1) fail(`${label} must not be a placeholder commit`);
  return value;
}

function review(value, label, context) {
  exactObject(value, ["approved", "approvedBy", "approvedAt"], label);
  booleanTrue(value.approved, `${label}.approved`);
  text(value.approvedBy, `${label}.approvedBy`, context, { min: 3, max: 160 });
  if (!context.allowContractFixture && REVIEW_PLACEHOLDER.test(value.approvedBy)) {
    fail(`${label}.approvedBy must identify an accountable reviewer, not a fixture identity`);
  }
  text(value.approvedAt, `${label}.approvedAt`, context, {
    pattern: /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/,
  });
  if (Number.isNaN(Date.parse(value.approvedAt))) fail(`${label}.approvedAt must be a valid UTC timestamp`);
}

function containedArtifactPath(relativePath, label, context) {
  text(relativePath, `${label}.path`, context, { min: 3, max: 360 });
  if (path.isAbsolute(relativePath) || relativePath.includes("\\") || relativePath.split("/").includes("..")) {
    fail(`${label}.path must be a normalized repository-relative path`);
  }
  const normalized = path.posix.normalize(relativePath);
  if (normalized !== relativePath || normalized.startsWith("../")) fail(`${label}.path is not normalized`);
  if (
    context.evidenceClass === "release-evidence" &&
    normalized.startsWith(CONTRACT_FIXTURE_ARTIFACT_PREFIX)
  ) {
    fail(`${label}.path points to contract-fixture data, which is never product release evidence`);
  }
  if (context.artifactPaths.has(normalized)) fail(`${label}.path duplicates another evidence artifact: ${normalized}`);
  context.artifactPaths.add(normalized);
  const absolute = path.resolve(context.root, ...normalized.split("/"));
  const rootPrefix = `${context.root}${path.sep}`;
  if (absolute !== context.root && !absolute.startsWith(rootPrefix)) fail(`${label}.path escapes the repository root`);
  let stat;
  try {
    stat = lstatSync(absolute);
  } catch {
    fail(`${label}.path does not exist: ${normalized}`);
  }
  if (!stat.isFile() || stat.isSymbolicLink()) fail(`${label}.path must be a regular non-symlink file`);
  const real = realpathSync(absolute);
  if (real !== context.root && !real.startsWith(rootPrefix)) fail(`${label}.path resolves outside the repository root`);
  return { absolute, normalized, stat };
}

function artifact(value, label, context) {
  exactObject(value, ["path", "sha256", "bytes"], label);
  const located = containedArtifactPath(value.path, label, context);
  sha256(value.sha256, `${label}.sha256`);
  integer(value.bytes, `${label}.bytes`, 1);
  if (located.stat.size !== value.bytes) fail(`${label}.bytes does not match the artifact byte count`);
  const actualHash = createHash("sha256").update(readFileSync(located.absolute)).digest("hex");
  if (actualHash !== value.sha256) fail(`${label}.sha256 does not match the artifact bytes`);
  return located.absolute;
}

function artifactJson(value, label, context) {
  const absolute = artifact(value, label, context);
  return parseStrictJson(readFileSync(absolute, "utf8"), `${label} (${value.path})`);
}

function repositorySource(value, label, context) {
  exactObject(value, ["repository", "commit", "archive"], label);
  const repository = text(value.repository, `${label}.repository`, context, { pattern: /^https:\/\/[^\s?#]+$/ });
  if (!context.allowContractFixture && new URL(repository).hostname.endsWith(".invalid")) {
    fail(`${label}.repository cannot use a reserved test domain`);
  }
  commit(value.commit, `${label}.commit`);
  artifact(value.archive, `${label}.archive`, context);
}

function redistribution(value, label, context) {
  exactObject(value, ["approved", "basis", "evidence", "review"], label);
  booleanTrue(value.approved, `${label}.approved`);
  if (!["rights-holder-permission", "qualified-legal-review"].includes(value.basis)) {
    fail(`${label}.basis must be rights-holder-permission or qualified-legal-review`);
  }
  artifact(value.evidence, `${label}.evidence`, context);
  review(value.review, `${label}.review`, context);
}

function validateRights(value, context) {
  exactObject(value, ["supremIvGs", "supremPatches", "devsim", "gmsh", "transitiveRuntime"], "rights");

  exactObject(value.supremIvGs, ["source", "licenseText", "redistribution"], "rights.supremIvGs");
  repositorySource(value.supremIvGs.source, "rights.supremIvGs.source", context);
  artifact(value.supremIvGs.licenseText, "rights.supremIvGs.licenseText", context);
  redistribution(value.supremIvGs.redistribution, "rights.supremIvGs.redistribution", context);

  exactObject(
    value.supremPatches,
    ["patchSet", "provenance", "ownershipEvidence", "redistribution"],
    "rights.supremPatches",
  );
  artifact(value.supremPatches.patchSet, "rights.supremPatches.patchSet", context);
  artifact(value.supremPatches.provenance, "rights.supremPatches.provenance", context);
  artifact(value.supremPatches.ownershipEvidence, "rights.supremPatches.ownershipEvidence", context);
  redistribution(value.supremPatches.redistribution, "rights.supremPatches.redistribution", context);

  exactObject(
    value.devsim,
    ["version", "source", "binarySha256", "licenseText", "notice", "obligationsReview"],
    "rights.devsim",
  );
  text(value.devsim.version, "rights.devsim.version", context);
  repositorySource(value.devsim.source, "rights.devsim.source", context);
  sha256(value.devsim.binarySha256, "rights.devsim.binarySha256");
  artifact(value.devsim.licenseText, "rights.devsim.licenseText", context);
  artifact(value.devsim.notice, "rights.devsim.notice", context);
  review(value.devsim.obligationsReview, "rights.devsim.obligationsReview", context);

  exactObject(
    value.gmsh,
    ["version", "source", "binarySha256", "licenseText", "notice", "correspondingSource", "obligationsReview"],
    "rights.gmsh",
  );
  text(value.gmsh.version, "rights.gmsh.version", context);
  repositorySource(value.gmsh.source, "rights.gmsh.source", context);
  sha256(value.gmsh.binarySha256, "rights.gmsh.binarySha256");
  artifact(value.gmsh.licenseText, "rights.gmsh.licenseText", context);
  artifact(value.gmsh.notice, "rights.gmsh.notice", context);
  artifact(value.gmsh.correspondingSource, "rights.gmsh.correspondingSource", context);
  review(value.gmsh.obligationsReview, "rights.gmsh.obligationsReview", context);

  exactObject(
    value.transitiveRuntime,
    ["packageLicenseReport", "notices", "unresolvedLicenseCount", "obligationsReview"],
    "rights.transitiveRuntime",
  );
  artifact(value.transitiveRuntime.packageLicenseReport, "rights.transitiveRuntime.packageLicenseReport", context);
  artifact(value.transitiveRuntime.notices, "rights.transitiveRuntime.notices", context);
  if (value.transitiveRuntime.unresolvedLicenseCount !== 0) {
    fail("rights.transitiveRuntime.unresolvedLicenseCount must be exactly zero");
  }
  review(value.transitiveRuntime.obligationsReview, "rights.transitiveRuntime.obligationsReview", context);
}

function immutableReference(value, expectedDigest, label, context) {
  text(value, label, context, { min: 75, max: 512 });
  const marker = `@${expectedDigest}`;
  if (!value.endsWith(marker) || value.indexOf("@") !== value.lastIndexOf("@")) {
    fail(`${label} must end with its exact sha256 digest and contain one '@' separator`);
  }
  const repository = value.slice(0, -marker.length);
  const lastSlash = repository.lastIndexOf("/");
  if (!repository.includes("/") || repository.slice(lastSlash + 1).includes(":")) {
    fail(`${label} must be an immutable repository reference without a mutable tag`);
  }
}

function validateSbom(value, label, platformDigest, context) {
  exactObject(value, ["format", "artifact", "subjectDigest", "scanner", "licenseReview"], label);
  if (value.format !== "cyclonedx-json") fail(`${label}.format must be cyclonedx-json`);
  if (value.subjectDigest !== platformDigest) fail(`${label}.subjectDigest must equal the platform manifest digest`);
  const sbom = artifactJson(value.artifact, `${label}.artifact`, context);
  exactObject(value.scanner, ["name", "version", "imageReference"], `${label}.scanner`);
  text(value.scanner.name, `${label}.scanner.name`, context);
  text(value.scanner.version, `${label}.scanner.version`, context);
  const scannerDigest = value.scanner.imageReference.slice(value.scanner.imageReference.lastIndexOf("@") + 1);
  digest(scannerDigest, `${label}.scanner.imageReference digest`);
  immutableReference(value.scanner.imageReference, scannerDigest, `${label}.scanner.imageReference`, context);
  review(value.licenseReview, `${label}.licenseReview`, context);

  if (sbom?.bomFormat !== "CycloneDX" || !["1.6", "1.7"].includes(sbom.specVersion)) {
    fail(`${label}.artifact must be a CycloneDX 1.6 or 1.7 JSON document`);
  }
  const properties = sbom?.metadata?.component?.properties;
  if (!Array.isArray(properties)) fail(`${label}.artifact must contain metadata.component.properties`);
  const bindings = properties.filter(
    (entry) => entry?.name === "opentcad:subject-manifest-digest" && entry?.value === platformDigest,
  );
  if (bindings.length !== 1) fail(`${label}.artifact must bind exactly once to its platform manifest digest`);
}

function validateImages(value, context) {
  const images = exactArray(value, "images", IMAGE_ROLES.length);
  if (images.length !== IMAGE_ROLES.length) fail(`images must contain exactly ${IMAGE_ROLES.length} entries`);
  const byRole = new Map();
  for (const [index, image] of images.entries()) {
    const label = `images[${index}]`;
    exactObject(image, ["id", "role", "reference", "indexDigest", "recipe", "reproducibility", "platforms"], label);
    text(image.id, `${label}.id`, context);
    if (!IMAGE_ROLES.includes(image.role)) fail(`${label}.role is not a required image role`);
    if (byRole.has(image.role)) fail(`${label}.role duplicates ${image.role}`);
    digest(image.indexDigest, `${label}.indexDigest`);
    immutableReference(image.reference, image.indexDigest, `${label}.reference`, context);
    artifact(image.recipe, `${label}.recipe`, context);
    exactObject(
      image.reproducibility,
      ["buildCount", "identicalIndexDigest", "evidence", "review"],
      `${label}.reproducibility`,
    );
    integer(image.reproducibility.buildCount, `${label}.reproducibility.buildCount`, 2);
    booleanTrue(image.reproducibility.identicalIndexDigest, `${label}.reproducibility.identicalIndexDigest`);
    artifact(image.reproducibility.evidence, `${label}.reproducibility.evidence`, context);
    review(image.reproducibility.review, `${label}.reproducibility.review`, context);

    if (!Array.isArray(image.platforms) || image.platforms.length !== RELEASE_PLATFORMS.length) {
      fail(`${label}.platforms must contain exactly ${RELEASE_PLATFORMS.join(" and ")}`);
    }
    const platforms = image.platforms;
    const platformMap = new Map();
    for (const [platformIndex, platform] of platforms.entries()) {
      const platformLabel = `${label}.platforms[${platformIndex}]`;
      exactObject(platform, ["platform", "manifestDigest", "sbom"], platformLabel);
      if (!RELEASE_PLATFORMS.includes(platform.platform)) {
        fail(`${platformLabel}.platform must be linux/amd64 or linux/arm64`);
      }
      if (platformMap.has(platform.platform)) fail(`${platformLabel}.platform is duplicated`);
      digest(platform.manifestDigest, `${platformLabel}.manifestDigest`);
      validateSbom(platform.sbom, `${platformLabel}.sbom`, platform.manifestDigest, context);
      platformMap.set(platform.platform, platform.manifestDigest);
    }
    equalSets(new Set(platformMap.keys()), new Set(RELEASE_PLATFORMS), `${label}.platforms platform set`);
    byRole.set(image.role, { ...image, platformMap });
  }
  for (const role of IMAGE_ROLES) if (!byRole.has(role)) fail(`images is missing the ${role} role`);
  return byRole;
}

function stringSet(value, label, context) {
  const array = exactArray(value, label);
  const result = new Set();
  for (const [index, item] of array.entries()) {
    text(item, `${label}[${index}]`, context, { min: 1, max: 128 });
    if (result.has(item)) fail(`${label} contains duplicate value ${item}`);
    result.add(item);
  }
  return result;
}

function equalSets(actual, expected, label) {
  if (actual.size !== expected.size || [...actual].some((value) => !expected.has(value))) {
    fail(`${label} must match the declared contract exactly`);
  }
}

function validateCorpusCase(value, label, baselineId, images, context) {
  exactObject(
    value,
    [
      "id",
      "engine",
      "input",
      "expected",
      "provenance",
      "results",
      "requiredComparators",
      "tolerances",
      "repeats",
      "warningPolicy",
      "review",
    ],
    label,
  );
  text(value.id, `${label}.id`, context, { min: 3, max: 128 });
  if (!CORPUS_ENGINES.includes(value.engine)) fail(`${label}.engine is not SUPREM-IV.GS, DEVSIM, or Gmsh`);
  artifact(value.input, `${label}.input`, context);
  artifact(value.expected, `${label}.expected`, context);
  const provenance = artifactJson(value.provenance, `${label}.provenance`, context);
  const results = artifactJson(value.results, `${label}.results`, context);
  const requiredComparators = stringSet(value.requiredComparators, `${label}.requiredComparators`, context);
  integer(value.repeats, `${label}.repeats`, 5);

  const toleranceMetrics = new Set();
  for (const [index, tolerance] of exactArray(value.tolerances, `${label}.tolerances`).entries()) {
    const toleranceLabel = `${label}.tolerances[${index}]`;
    exactObject(tolerance, ["metric", "unit", "absolute", "relative", "rationale"], toleranceLabel);
    text(tolerance.metric, `${toleranceLabel}.metric`, context);
    text(tolerance.unit, `${toleranceLabel}.unit`, context);
    if (typeof tolerance.absolute !== "number" || !Number.isFinite(tolerance.absolute) || tolerance.absolute < 0) {
      fail(`${toleranceLabel}.absolute must be a finite non-negative number`);
    }
    if (typeof tolerance.relative !== "number" || !Number.isFinite(tolerance.relative) || tolerance.relative < 0) {
      fail(`${toleranceLabel}.relative must be a finite non-negative number`);
    }
    text(tolerance.rationale, `${toleranceLabel}.rationale`, context, { min: 12, max: 512 });
    if (toleranceMetrics.has(tolerance.metric)) fail(`${toleranceLabel}.metric is duplicated`);
    toleranceMetrics.add(tolerance.metric);
  }

  exactObject(value.warningPolicy, ["mode", "allowedCodes"], `${label}.warningPolicy`);
  if (value.warningPolicy.mode !== "fail-unlisted") fail(`${label}.warningPolicy.mode must be fail-unlisted`);
  const allowedWarnings = new Set();
  if (!Array.isArray(value.warningPolicy.allowedCodes)) fail(`${label}.warningPolicy.allowedCodes must be an array`);
  for (const [index, code] of value.warningPolicy.allowedCodes.entries()) {
    text(code, `${label}.warningPolicy.allowedCodes[${index}]`, context, { max: 128 });
    if (allowedWarnings.has(code)) fail(`${label}.warningPolicy.allowedCodes contains a duplicate`);
    allowedWarnings.add(code);
  }
  review(value.review, `${label}.review`, context);

  exactObject(
    provenance,
    [
      "schemaVersion",
      "caseId",
      "engine",
      "inputSha256",
      "expectedSha256",
      "imageRole",
      "imageIndexDigest",
      "platform",
      "platformManifestDigest",
      "engineVersion",
    ],
    `${label}.provenance document`,
  );
  if (provenance.schemaVersion !== 1) fail(`${label}.provenance.schemaVersion must be 1`);
  if (provenance.caseId !== value.id || provenance.engine !== value.engine) fail(`${label}.provenance does not identify its case`);
  if (provenance.inputSha256 !== value.input.sha256 || provenance.expectedSha256 !== value.expected.sha256) {
    fail(`${label}.provenance does not bind the exact input and expected artifacts`);
  }
  const role = ENGINE_ROLE.get(value.engine);
  if (provenance.imageRole !== role) fail(`${label}.provenance.imageRole must be ${role}`);
  const image = images.get(role);
  if (provenance.imageIndexDigest !== image.indexDigest) fail(`${label}.provenance.imageIndexDigest does not match the release image`);
  if (!RELEASE_PLATFORMS.includes(provenance.platform)) {
    fail(`${label}.provenance.platform must be linux/amd64 or linux/arm64`);
  }
  if (image.platformMap.get(provenance.platform) !== provenance.platformManifestDigest) {
    fail(`${label}.provenance platform manifest is not in the release image index`);
  }
  text(provenance.engineVersion, `${label}.provenance.engineVersion`, context);

  exactObject(
    results,
    ["schemaVersion", "caseId", "baselineId", "status", "repeats", "comparators", "metrics", "warningCodes"],
    `${label}.results document`,
  );
  if (results.schemaVersion !== 1 || results.caseId !== value.id || results.baselineId !== baselineId) {
    fail(`${label}.results does not identify its case and baseline`);
  }
  if (results.status !== "passed") fail(`${label}.results.status must be passed`);
  if (!Number.isInteger(results.repeats) || results.repeats < value.repeats) {
    fail(`${label}.results.repeats must satisfy the declared repeat count`);
  }
  equalSets(stringSet(results.comparators, `${label}.results.comparators`, context), requiredComparators, `${label}.results.comparators`);
  equalSets(stringSet(results.metrics, `${label}.results.metrics`, context), toleranceMetrics, `${label}.results.metrics`);
  if (!Array.isArray(results.warningCodes)) fail(`${label}.results.warningCodes must be an array`);
  const observedWarnings = new Set();
  for (const [index, code] of results.warningCodes.entries()) {
    text(code, `${label}.results.warningCodes[${index}]`, context, { max: 128 });
    if (observedWarnings.has(code)) fail(`${label}.results.warningCodes contains a duplicate`);
    if (!allowedWarnings.has(code)) fail(`${label}.results contains an unlisted warning code`);
    observedWarnings.add(code);
  }
}

function validateCorpus(value, images, context) {
  exactObject(value, ["baselineId", "cases", "review"], "numericalCorpus");
  text(value.baselineId, "numericalCorpus.baselineId", context, { min: 4, max: 128 });
  const engines = new Set();
  const ids = new Set();
  for (const [index, corpusCase] of exactArray(value.cases, "numericalCorpus.cases", CORPUS_ENGINES.length).entries()) {
    validateCorpusCase(corpusCase, `numericalCorpus.cases[${index}]`, value.baselineId, images, context);
    if (ids.has(corpusCase.id)) fail(`numericalCorpus.cases[${index}].id is duplicated`);
    if (engines.has(corpusCase.engine)) fail(`numericalCorpus.cases[${index}].engine is duplicated`);
    ids.add(corpusCase.id);
    engines.add(corpusCase.engine);
  }
  equalSets(engines, new Set(CORPUS_ENGINES), "numericalCorpus.cases engines");
  review(value.review, "numericalCorpus.review", context);
}

export function validateSolverReleaseDocument(value, options = {}) {
  const root = realpathSync(path.resolve(options.root ?? process.cwd()));
  const context = {
    root,
    artifactPaths: new Set(),
    allowContractFixture: options.allowContractFixture === true,
  };
  exactObject(
    value,
    [
      "schemaVersion",
      "evidenceClass",
      "releaseId",
      "productVersion",
      "productManifestSha256",
      "status",
      "rights",
      "images",
      "numericalCorpus",
      "releaseReview",
    ],
    "solver release evidence",
  );
  if (value.schemaVersion !== 1) fail("schemaVersion must be 1");
  if (value.evidenceClass === "contract-fixture") {
    if (!context.allowContractFixture) fail("contract-fixture evidence is never accepted for a product release");
  } else if (value.evidenceClass !== "release-evidence") {
    fail("evidenceClass must be release-evidence");
  }
  context.evidenceClass = value.evidenceClass;
  text(value.releaseId, "releaseId", context, { min: 4, max: 128 });
  text(value.productVersion, "productVersion", context, { min: 1, max: 128 });
  sha256(value.productManifestSha256, "productManifestSha256");
  if (value.status !== "approved") fail("status must be approved; partial or blocked evidence cannot be promoted");
  validateRights(value.rights, context);
  const images = validateImages(value.images, context);
  validateCorpus(value.numericalCorpus, images, context);
  review(value.releaseReview, "releaseReview", context);
  return Object.freeze({
    releaseId: value.releaseId,
    productVersion: value.productVersion,
    evidenceClass: value.evidenceClass,
    artifactCount: context.artifactPaths.size,
  });
}

export function validateSolverReleaseFile(candidatePath, options = {}) {
  const absolute = path.resolve(options.root ?? process.cwd(), candidatePath);
  const source = readFileSync(absolute, "utf8");
  const value = parseStrictJson(source, candidatePath);
  return validateSolverReleaseDocument(value, options);
}

function parseArguments(argv) {
  let candidate;
  let root = process.cwd();
  for (let index = 0; index < argv.length; index += 1) {
    if (argv[index] === "--candidate" && argv[index + 1]) {
      candidate = argv[index + 1];
      index += 1;
    } else if (argv[index] === "--root" && argv[index + 1]) {
      root = argv[index + 1];
      index += 1;
    } else {
      fail(`unknown or incomplete argument: ${argv[index]}`);
    }
  }
  if (!candidate) fail("usage: node tools/check-m3-solver-release.mjs --candidate <reviewed-evidence.json> [--root <repository>]");
  return { candidate, root };
}

export function runSolverReleaseCli(argv, output = console) {
  try {
    const { candidate, root } = parseArguments(argv);
    const result = validateSolverReleaseFile(candidate, { root, allowContractFixture: false });
    output.log(
      `M3 solver release evidence approved: ${result.releaseId} (${result.productVersion}); ${result.artifactCount} artifacts verified.`,
    );
    return 0;
  } catch (error) {
    output.error(`M3 solver release evidence rejected: ${error.message}`);
    return 1;
  }
}

function main() {
  process.exitCode = runSolverReleaseCli(process.argv.slice(2));
}

if (process.argv[1] && pathToFileURL(fileURLToPath(pathToFileURL(process.argv[1]))).href === import.meta.url) main();
