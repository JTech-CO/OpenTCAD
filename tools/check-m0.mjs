import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const inventoryPath = join(projectRoot, "m0", "DEPENDENCY_AND_IMAGE_INVENTORY.json");
const baselinePath = join(projectRoot, "m0", "BASELINE_FREEZE.json");

const inventory = JSON.parse(await readFile(inventoryPath, "utf8"));
const baseline = JSON.parse(await readFile(baselinePath, "utf8"));
const errors = [];

function requireValue(condition, message) {
  if (!condition) errors.push(message);
}

function uniqueIds(items, label) {
  const ids = items.map(({ id }) => id);
  requireValue(new Set(ids).size === ids.length, `${label} contains duplicate ids.`);
}

requireValue(inventory.schemaVersion === 1, "Unsupported M0 inventory schema.");
requireValue(baseline.schemaVersion === 1, "Unsupported M0 baseline schema.");
requireValue(
  inventory.distributionBoundary.repositoryContainsSolverSourceOrBinary === false,
  "The M0 distribution boundary must not claim bundled solver artifacts.",
);

uniqueIds(inventory.components, "Component inventory");
uniqueIds(inventory.images, "Image inventory");
uniqueIds(baseline.references, "Baseline references");
uniqueIds(baseline.goldenCaseCandidates, "Golden case candidates");

for (const component of inventory.components) {
  requireValue(component.licenseEvidence, `${component.id} has no license evidence.`);
  if (component.distributionStatus === "approved") {
    requireValue(
      !component.license.toLowerCase().includes("unresolved"),
      `${component.id} cannot be approved with an unresolved license.`,
    );
  }
}

for (const image of inventory.images) {
  if (image.distributionStatus === "approved") {
    requireValue(
      typeof image.digest === "string" && image.digest.startsWith("sha256:"),
      `${image.id} cannot be approved without an immutable digest.`,
    );
  }
}

for (const reference of baseline.references) {
  requireValue(/^[0-9a-f]{40}$/.test(reference.commit), `${reference.id} has an invalid commit id.`);
}

requireValue(
  baseline.solverExecutionBaseline.status !== "verified" ||
    baseline.solverExecutionBaseline.requiredEvidence.length > 0,
  "A verified solver baseline must retain its evidence requirements.",
);

const localHashes = inventory.evidenceHashes.filter(({ repository }) => repository === "OpenTCAD");
for (const evidence of localHashes) {
  const bytes = await readFile(join(projectRoot, evidence.path));
  const actual = createHash("sha256").update(bytes).digest("hex");
  requireValue(actual === evidence.sha256, `${evidence.path} no longer matches the M0 evidence hash.`);
}

const bilingualPairs = [
  ["docs/en/m0/README.md", "docs/ko/m0/README.md"],
  ["docs/en/m0/license-strategy.md", "docs/ko/m0/license-strategy.md"],
  ["docs/en/m0/baseline-and-clean-room.md", "docs/ko/m0/baseline-and-clean-room.md"],
  ["docs/en/m0/current-architecture.md", "docs/ko/m0/current-architecture.md"],
  ["docs/en/m0/portability-spike-report.md", "docs/ko/m0/portability-spike-report.md"],
];

for (const pair of bilingualPairs.flat()) {
  try {
    await readFile(join(projectRoot, pair), "utf8");
  } catch {
    errors.push(`Missing bilingual M0 document: ${pair}`);
  }
}

if (errors.length > 0) {
  console.error("M0 evidence check failed:");
  errors.forEach((error) => console.error(`- ${error}`));
  process.exitCode = 1;
} else {
  console.log(
    `M0 evidence check passed (${inventory.components.length} components, ${inventory.images.length} images, ${baseline.references.length} frozen references).`,
  );
}
