import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { COMPARATOR_IDS } from "../validation/comparators/index.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const errors = [];

async function readJson(relativePath) {
  return JSON.parse(await readFile(join(root, relativePath), "utf8"));
}

function requireValue(condition, message) {
  if (!condition) errors.push(message);
}

function requireUnique(items, label) {
  requireValue(new Set(items).size === items.length, `${label} contains duplicates.`);
}

async function sha256(relativePath) {
  const bytes = await readFile(join(root, relativePath));
  return createHash("sha256").update(bytes).digest("hex");
}

const [foundation, corpus, imageLock, m0Baseline, m0Inventory, packageJson] = await Promise.all([
  readJson("validation/manifests/m1-foundation.json"),
  readJson("validation/corpus/index.json"),
  readJson("validation/manifests/image-lock.json"),
  readJson("m0/BASELINE_FREEZE.json"),
  readJson("m0/DEPENDENCY_AND_IMAGE_INVENTORY.json"),
  readJson("package.json"),
]);

requireValue(foundation.schemaVersion === 1, "Unsupported M1 foundation schema.");
requireValue(foundation.status === "gated-active", "M1 must remain gated-active until M0 entry conditions pass.");
requireValue(foundation.entryConditions.overall === "not-met", "M1 entry conditions are not evidenced as met.");
requireValue(foundation.exitCriteria.overall === "not-met", "M1 exit must remain not-met.");
requireValue(foundation.baselinePolicy.automaticUpdateAllowed === false, "Automatic baseline updates are forbidden.");
requireValue(foundation.baselinePolicy.ciMayWriteGoldenArtifacts === false, "CI must not write golden artifacts.");

const evidencePairs = [
  [foundation.m0Evidence.baselineFreezePath, foundation.m0Evidence.baselineFreezeSha256],
  [foundation.m0Evidence.dependencyInventoryPath, foundation.m0Evidence.dependencyInventorySha256],
  [imageLock.sourceInventory.path, imageLock.sourceInventory.sha256],
];
for (const [path, expectedHash] of evidencePairs) {
  requireValue((await sha256(path)) === expectedHash, `${path} does not match the M1 evidence hash.`);
}

requireValue(m0Baseline.m0Exit.overall === "not-met", "The M0 record unexpectedly claims completion.");
requireValue(corpus.schemaVersion === 1, "Unsupported corpus schema.");
requireValue(corpus.status === "candidate-only", "Corpus must remain candidate-only before a real baseline.");
requireValue(corpus.baselineId === null, "Candidate corpus must not claim a baseline id.");
requireValue(corpus.automaticBaselineUpdateAllowed === false, "Corpus must forbid automatic baseline updates.");

const requiredCaseIds = [
  "process-1d-boron",
  "process-1d-oxidation",
  "process-1d-implant",
  "process-2d-nmos",
  "process-2d-cmos-mask-interface",
  "str-parser-topology",
  "gmsh-remesh",
  "devsim-diode",
  "devsim-nmos-idvg",
  "devsim-nmos-idvd",
  "devsim-cmos-load-line",
];
const caseIds = corpus.cases.map(({ id }) => id);
requireUnique(caseIds, "Corpus case ids");
requireValue(
  requiredCaseIds.every((id) => caseIds.includes(id)),
  "Corpus does not cover every required M1 candidate case.",
);

for (const candidate of corpus.cases) {
  requireValue(candidate.baselineStatus === "pending-m0", `${candidate.id} cannot be frozen before M0 evidence.`);
  requireValue(candidate.expected === null, `${candidate.id} must not contain invented expected values.`);
  requireValue(candidate.source.status === "not-in-repository", `${candidate.id} source must remain quarantined.`);
  requireValue(candidate.source.path === null, `${candidate.id} must not point to an unfrozen fixture.`);
  requireValue(candidate.source.sha256 === null, `${candidate.id} must not claim an input hash.`);
  requireValue(candidate.warningPolicy.mode === "fail-unlisted", `${candidate.id} must fail unlisted warnings.`);
  requireUnique(candidate.requiredComparators, `${candidate.id} comparator list`);
  requireUnique(candidate.requiredMetrics, `${candidate.id} metric list`);
  for (const comparator of candidate.requiredComparators) {
    requireValue(COMPARATOR_IDS.includes(comparator), `${candidate.id} requests unknown comparator ${comparator}.`);
  }
}

requireValue(imageLock.status === "blocked-m0", "Image lock must remain blocked until immutable evidence exists.");
const m0Images = new Map(m0Inventory.images.map((image) => [image.id, image]));
requireUnique(imageLock.images.map(({ id }) => id), "Image lock ids");
requireValue(imageLock.images.length === m0Images.size, "Image lock must cover every M0 image definition.");

for (const image of imageLock.images) {
  const source = m0Images.get(image.id);
  requireValue(source, `Image ${image.id} is absent from the M0 inventory.`);
  if (!source) continue;
  requireValue(image.reference === source.reference, `${image.id} reference differs from M0.`);
  requireValue(image.digest === source.digest, `${image.id} digest differs from M0.`);
  requireValue(image.digest === null, `${image.id} must not claim an unverified digest.`);
  requireValue(image.releaseApproved === false, `${image.id} must not be release-approved.`);
  requireValue(image.sbomSha256 === null, `${image.id} must not claim an SBOM before generation.`);
}

const scriptValues = Object.values(packageJson.scripts ?? {});
requireValue(
  scriptValues.every((script) => !/update.*baseline|baseline.*update/i.test(script)),
  "package.json must not expose an automatic baseline update command.",
);

const bilingualPairs = [
  ["docs/en/m1/README.md", "docs/ko/m1/README.md"],
  ["docs/en/m1/validation-contract.md", "docs/ko/m1/validation-contract.md"],
  ["validation/README.md", "validation/README.ko.md"],
];
for (const relativePath of bilingualPairs.flat()) {
  try {
    await readFile(join(root, relativePath), "utf8");
  } catch {
    errors.push(`Missing bilingual M1 document: ${relativePath}`);
  }
}

for (const relativePath of [
  "validation/schemas/corpus.schema.json",
  "validation/schemas/report.schema.json",
]) {
  try {
    await readJson(relativePath);
  } catch {
    errors.push(`Missing or invalid validation schema: ${relativePath}`);
  }
}

if (errors.length > 0) {
  console.error("M1 foundation check failed:");
  errors.forEach((error) => console.error(`- ${error}`));
  process.exitCode = 1;
} else {
  console.log(
    `M1 foundation check passed (${corpus.cases.length} candidate cases, ${COMPARATOR_IDS.length} comparators, ${imageLock.images.length} quarantined images).`,
  );
}
