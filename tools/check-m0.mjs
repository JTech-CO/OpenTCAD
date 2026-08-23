import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { validateReferenceImageBuildPlan } from "../validation/baseline/reference-image-build.mjs";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const inventoryPath = join(projectRoot, "m0", "DEPENDENCY_AND_IMAGE_INVENTORY.json");
const baselinePath = join(projectRoot, "m0", "BASELINE_FREEZE.json");
const observationPath = join(projectRoot, "m0", "BASE001_DOCKER_OBSERVATION.json");
const rootlessObservationPath = join(
  projectRoot,
  "m0",
  "BASE001_ROOTLESS_PODMAN_OBSERVATION.json",
);
const observationPlanPath = join(
  projectRoot,
  "validation",
  "plans",
  "base001-process-1d-boron.json",
);
const imageBuildPlanPath = join(
  projectRoot,
  "validation",
  "plans",
  "base001-suprem-image-build.json",
);
const imageBuildObservationPath = join(
  projectRoot,
  "m0",
  "BASE001_REPRODUCIBLE_IMAGE_OBSERVATION.json",
);

const inventory = JSON.parse(await readFile(inventoryPath, "utf8"));
const baseline = JSON.parse(await readFile(baselinePath, "utf8"));
const observation = JSON.parse(await readFile(observationPath, "utf8"));
const rootlessObservation = JSON.parse(await readFile(rootlessObservationPath, "utf8"));
const observationPlan = JSON.parse(await readFile(observationPlanPath, "utf8"));
const imageBuildPlanBytes = await readFile(imageBuildPlanPath);
const imageBuildPlan = JSON.parse(imageBuildPlanBytes.toString("utf8"));
const imageBuildObservation = JSON.parse(await readFile(imageBuildObservationPath, "utf8"));
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
requireValue(observation.schemaVersion === 1, "Unsupported BASE-001 Docker observation schema.");
requireValue(
  rootlessObservation.schemaVersion === 1,
  "Unsupported BASE-001 rootless Podman observation schema.",
);
requireValue(
  imageBuildObservation.schemaVersion === 1,
  "Unsupported BASE-001 reproducible image observation schema.",
);
requireValue(observationPlan.schemaVersion === 1, "Unsupported BASE-001 plan schema.");
try {
  validateReferenceImageBuildPlan(imageBuildPlan);
} catch (error) {
  errors.push(error instanceof Error ? error.message : String(error));
}
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

const behaviorReference = baseline.references.find(({ id }) => id === "behavior-reference");
requireValue(
  observationPlan.baselinePromotionAllowed === false,
  "BASE-001 observation plans must forbid automatic promotion.",
);
requireValue(
  observationPlan.reference.commit === behaviorReference?.commit,
  "The BASE-001 plan must use the frozen behavior reference.",
);
requireValue(
  observationPlan.requiredProfile.runtime === "podman" &&
    observationPlan.requiredProfile.operatingSystem === "linux" &&
    observationPlan.requiredProfile.architecture === "amd64" &&
    observationPlan.requiredProfile.rootless === true,
  "The BASE-001 plan must retain the Linux amd64 rootless Podman profile.",
);
requireValue(
  observationPlan.invocation.repeats >= 5,
  "The BASE-001 plan must require at least five runs.",
);
const observationArgs = observationPlan.invocation.args;
for (const [flag, expected] of [
  ["--network", "none"],
  ["--cap-drop", "ALL"],
  ["--security-opt", "no-new-privileges"],
]) {
  const index = observationArgs.indexOf(flag);
  requireValue(
    index >= 0 &&
      observationArgs[index + 1] === expected &&
      observationArgs.indexOf(flag, index + 1) < 0,
    `The BASE-001 plan must use exactly one ${flag} ${expected}.`,
  );
}
requireValue(
  observationArgs.includes("--rm") &&
    observationArgs.includes("--read-only") &&
    observationArgs.includes("--interactive") &&
    observationArgs.includes("--pids-limit") &&
    observationArgs.includes("--memory") &&
    observationArgs.includes("--cpus"),
  "The BASE-001 plan is missing a required isolation or resource flag.",
);
const observationMounts = observationArgs.flatMap((argument, index) =>
  argument === "--mount" ? [observationArgs[index + 1]] : [],
);
requireValue(
  observationMounts.length === 1 &&
    observationMounts[0] === "type=bind,source={runDir},target=/work",
  "The BASE-001 plan must mount only its external run directory.",
);
requireValue(
  observationPlan.logPolicy.mode === "fail-on-match" &&
    observationPlan.logPolicy.failurePatterns.length > 0,
  "The BASE-001 plan must fail on declared log findings.",
);
requireValue(
  observationPlan.image.distribution === "local-reference-only-not-for-publication",
  "The observed reference image must remain local and unpublished.",
);
requireValue(
  !JSON.stringify(observationPlan).includes('"expected"'),
  "The observation plan must not contain an expected or golden value.",
);
for (const descriptor of [...observationPlan.inputs, ...observationPlan.artifacts]) {
  requireValue(
    !/^(?:[A-Za-z]:[\\/]|[\\/])/u.test(descriptor.relativePath) &&
      !descriptor.relativePath.split(/[\\/]+/u).includes(".."),
    `Observation path must be portable and confined: ${descriptor.relativePath}`,
  );
}

requireValue(
  observation.status === "observed-ineligible" &&
    observation.baselineEligibility === "ineligible" &&
    observation.baselinePromotionAllowed === false,
  "The Docker Desktop observation must remain explicitly ineligible.",
);
requireValue(
  observation.reference.commit === behaviorReference?.commit &&
    observation.reference.sourceOrBinaryCopiedIntoOpenTCAD === false,
  "The observation must retain the frozen reference and no-copy boundary.",
);
requireValue(
  observation.environment.observed.runtime === "docker" &&
    observation.environment.observed.rootless === false &&
    observation.environment.profileMismatches.includes("runtime") &&
    observation.environment.profileMismatches.includes("rootless"),
  "The nonconforming runtime and rootless findings must remain visible.",
);
requireValue(
  observation.build.reproducibleImage === false &&
    observation.build.firstImage.digest !== observation.build.noCacheRebuild.digest,
  "The no-cache image rebuild drift must not be represented as reproducible.",
);
requireValue(
  observation.sbom.packages > 0 &&
    observation.sbom.licenseReviewComplete === false &&
    observation.sbom.committed === false,
  "The SBOM must remain external and unapproved until license review.",
);
requireValue(
  observation.case.repeats >= 5 &&
    observation.case.exitCodes.every((exitCode) => exitCode === 0) &&
    observation.case.semanticStatus === "failed-declared-log-policy",
  "Exit code zero must not override the observed semantic failure.",
);
requireValue(
  observation.case.requiredArtifact.exactlyRepeatable === true &&
    observation.case.requiredArtifact.matchesFrozenReferenceFixtureGitBlob === true &&
    /^[0-9a-f]{64}$/u.test(observation.case.requiredArtifact.sha256),
  "The repeated structure evidence is incomplete.",
);
requireValue(
  /^[0-9a-f]{64}$/u.test(observation.externalEvidence.manifestSha256) &&
    observation.externalEvidence.rawArtifactsCommitted === false &&
    observation.externalEvidence.absolutePathRecorded === false,
  "External evidence must be hashed without committing raw artifacts or host paths.",
);

requireValue(
  observation.externalEvidence.collectorFiles.length === 3 &&
    new Set(observation.externalEvidence.collectorFiles.map(({ path }) => path)).size === 3,
  "The observation must identify the CLI, evidence library, and reviewed plan.",
);
for (const collectorFile of observation.externalEvidence.collectorFiles) {
  requireValue(
    !/^(?:[A-Za-z]:[\\/]|[\\/])/u.test(collectorFile.path) &&
      !collectorFile.path.split(/[\\/]+/u).includes(".."),
    `Collector path must stay inside OpenTCAD: ${collectorFile.path}`,
  );
  const bytes = await readFile(join(projectRoot, collectorFile.path));
  const actual = createHash("sha256").update(bytes).digest("hex");
  requireValue(
    actual === collectorFile.sha256,
    `Collector identity drifted after the observation: ${collectorFile.path}`,
  );
}
requireValue(
  observation.m0Result.base001Status === "pending" &&
    observation.m0Result.m0Exit === "not-met" &&
    baseline.solverExecutionBaseline.status === "pending" &&
    baseline.m0Exit.overall === "not-met",
  "The ineligible observation must not close BASE-001 or M0.",
);

requireValue(
  rootlessObservation.status === "observed-ineligible" &&
    rootlessObservation.baselineEligibility === "ineligible" &&
    rootlessObservation.baselinePromotionAllowed === false,
  "The rootless Podman observation must remain explicitly ineligible.",
);
requireValue(
  rootlessObservation.reference.commit === behaviorReference?.commit &&
    rootlessObservation.reference.sourceOrBinaryCopiedIntoOpenTCAD === false,
  "The rootless observation must retain the frozen reference and no-copy boundary.",
);
requireValue(
  rootlessObservation.environment.observed.runtime === "podman" &&
    rootlessObservation.environment.observed.operatingSystem === "linux" &&
    rootlessObservation.environment.observed.architecture === "amd64" &&
    rootlessObservation.environment.observed.rootless === true &&
    rootlessObservation.environment.meetsRequiredProfile === true &&
    rootlessObservation.environment.profileMismatches.length === 0,
  "The rootless Podman observation must retain its conforming runtime profile.",
);
requireValue(
  rootlessObservation.build.reproducibleImage === false &&
    rootlessObservation.build.firstImage.digest !==
      rootlessObservation.build.noCacheRebuild.digest &&
    /^sha256:[0-9a-f]{64}$/u.test(rootlessObservation.build.firstImage.digest) &&
    /^sha256:[0-9a-f]{64}$/u.test(rootlessObservation.build.noCacheRebuild.digest) &&
    rootlessObservation.build.noCacheRebuild.sameSolverBinary === true &&
    /^[0-9a-f]{64}$/u.test(rootlessObservation.build.solverBinarySha256),
  "The Podman image drift and stable solver-binary finding must remain visible.",
);
requireValue(
  rootlessObservation.sbom.status === "not-generated-for-podman-image" &&
    rootlessObservation.sbom.dockerObservationSbomReused === false &&
    rootlessObservation.sbom.licenseReviewComplete === false &&
    rootlessObservation.sbom.committed === false,
  "The missing Podman-image SBOM must not be represented as reviewed.",
);
requireValue(
  rootlessObservation.case.repeats >= 5 &&
    rootlessObservation.case.exitCodes.every((exitCode) => exitCode === 0) &&
    rootlessObservation.case.semanticStatus === "failed-declared-log-policy" &&
    rootlessObservation.case.stdout.exactlyRepeatable === true,
  "The Podman exit-code and semantic-failure evidence is incomplete.",
);
requireValue(
  rootlessObservation.case.requiredArtifact.exactlyRepeatable === true &&
    rootlessObservation.case.requiredArtifact.sha256 ===
      observation.case.requiredArtifact.sha256 &&
    JSON.stringify(rootlessObservation.case.recordCounts) ===
      JSON.stringify(observation.case.recordCounts),
  "The Docker and Podman structure evidence must remain exactly aligned.",
);
requireValue(
  Object.values(rootlessObservation.case.crossRuntimeComparison)
    .filter((value) => typeof value === "boolean")
    .every((value) => value === true) &&
    JSON.stringify(rootlessObservation.case.logFindingsPerRun) ===
      JSON.stringify(observation.case.logFindingsPerRun),
  "Every declared Docker-to-Podman comparison must remain exact.",
);
requireValue(
  /^[0-9a-f]{64}$/u.test(rootlessObservation.externalEvidence.manifestSha256) &&
    !Number.isNaN(Date.parse(rootlessObservation.externalEvidence.manifestRecordedAt)) &&
    rootlessObservation.externalEvidence.rawArtifactsCommitted === false &&
    rootlessObservation.externalEvidence.absolutePathRecorded === false,
  "Rootless external evidence must be hashed without committing raw artifacts or host paths.",
);
requireValue(
  rootlessObservation.externalEvidence.collectorFiles.length === 3 &&
    new Set(rootlessObservation.externalEvidence.collectorFiles.map(({ path }) => path)).size ===
      3,
  "The rootless observation must identify the CLI, evidence library, and reviewed plan.",
);
for (const collectorFile of rootlessObservation.externalEvidence.collectorFiles) {
  requireValue(
    !/^(?:[A-Za-z]:[\\/]|[\\/])/u.test(collectorFile.path) &&
      !collectorFile.path.split(/[\\/]+/u).includes(".."),
    `Rootless collector path must stay inside OpenTCAD: ${collectorFile.path}`,
  );
  const bytes = await readFile(join(projectRoot, collectorFile.path));
  const actual = createHash("sha256").update(bytes).digest("hex");
  requireValue(
    actual === collectorFile.sha256,
    `Rootless collector identity drifted after the observation: ${collectorFile.path}`,
  );
}
requireValue(
  rootlessObservation.m0Result.requiredProfileObserved === true &&
    rootlessObservation.m0Result.base001Status === "pending" &&
    rootlessObservation.m0Result.m0Exit === "not-met" &&
    baseline.solverExecutionBaseline.status === "pending" &&
    baseline.m0Exit.overall === "not-met",
  "The conforming profile observation must not close BASE-001 or M0.",
);
requireValue(
  !JSON.stringify(rootlessObservation).includes("/mnt/c/") &&
    !/[A-Za-z]:\\/.test(JSON.stringify(rootlessObservation)),
  "The sanitized rootless record must not contain an absolute host path.",
);
requireValue(
  imageBuildObservation.status === "observed-nonbaseline" &&
    imageBuildObservation.baselinePromotionAllowed === false &&
    imageBuildObservation.distributionAllowed === false,
  "The controlled image build must remain non-baseline and non-distributable.",
);
requireValue(
  imageBuildObservation.reference.commit === behaviorReference?.commit &&
    imageBuildObservation.reference.rawArchiveSha256 === imageBuildPlan.reference.rawArchiveSha256 &&
    imageBuildObservation.reference.sourceContainerfileSha256 ===
      imageBuildPlan.reference.containerfile.sha256 &&
    imageBuildObservation.reference.sourceTreeModified === false &&
    imageBuildObservation.reference.sourceOrBinaryCopiedIntoOpenTCAD === false,
  "The controlled build must retain its frozen external source boundary.",
);
const actualImageBuildPlanHash = createHash("sha256").update(imageBuildPlanBytes).digest("hex");
requireValue(
  imageBuildObservation.plan.path === "validation/plans/base001-suprem-image-build.json" &&
    imageBuildObservation.plan.sha256 === actualImageBuildPlanHash &&
    imageBuildObservation.plan.baselinePromotionAllowed === false &&
    imageBuildObservation.plan.distributionAllowed === false,
  "The controlled build plan identity or fail-closed flags drifted.",
);
requireValue(
  imageBuildObservation.environment.runtime === "podman" &&
    imageBuildObservation.environment.operatingSystem === "linux" &&
    imageBuildObservation.environment.architecture === "amd64" &&
    imageBuildObservation.environment.rootless === true,
  "The controlled build must retain the Linux amd64 rootless Podman environment.",
);
requireValue(
  imageBuildObservation.controls.pullPolicy === imageBuildPlan.build.pullPolicy &&
    imageBuildObservation.controls.noCache === imageBuildPlan.build.noCache &&
    imageBuildObservation.controls.format === imageBuildPlan.build.format &&
    imageBuildObservation.controls.timestampEpoch === imageBuildPlan.build.timestampEpoch &&
    imageBuildObservation.controls.sourceDateEpoch ===
      imageBuildPlan.build.environment.sourceDateEpoch &&
    imageBuildObservation.controls.locale === imageBuildPlan.build.environment.lcAll &&
    imageBuildObservation.controls.timezone === imageBuildPlan.build.environment.tz &&
    imageBuildObservation.controls.generatedContainerfile.committed === false,
  "The deterministic image controls drifted from the reviewed plan.",
);
requireValue(
  JSON.stringify(
    imageBuildObservation.controls.baseImages.map(({ stage, manifestDigest, indexDigest }) => ({
      stage,
      manifestDigest,
      indexDigest,
    })),
  ) ===
    JSON.stringify(
      imageBuildPlan.build.baseImages.map(({ stage, manifestDigest, indexDigest }) => ({
        stage,
        manifestDigest,
        indexDigest,
      })),
    ) &&
    JSON.stringify(imageBuildObservation.controls.aptSnapshots) ===
      JSON.stringify(imageBuildPlan.build.aptSnapshots.map(({ snapshot }) => snapshot)),
  "The base image or Debian snapshot pins drifted from the reviewed plan.",
);
const firstControlledImage = imageBuildObservation.builds.first;
const secondControlledImage = imageBuildObservation.builds.second;
requireValue(
  imageBuildObservation.builds.repeats >= 2 &&
    firstControlledImage.id === secondControlledImage.id &&
    firstControlledImage.digest === secondControlledImage.digest &&
    firstControlledImage.created === secondControlledImage.created &&
    firstControlledImage.bytes === secondControlledImage.bytes &&
    JSON.stringify(firstControlledImage.rootFilesystemLayers) ===
      JSON.stringify(secondControlledImage.rootFilesystemLayers) &&
    firstControlledImage.rootFilesystemLayers.length === 5 &&
    firstControlledImage.rootFilesystemLayers.every((digest) => /^sha256:[0-9a-f]{64}$/u.test(digest)) &&
    Object.values(imageBuildObservation.builds.comparison).every((value) => value === true),
  "The two no-cache image builds must remain byte-identical.",
);
requireValue(
  Date.parse(firstControlledImage.created) === imageBuildPlan.build.timestampEpoch * 1000 &&
    /^sha256:[0-9a-f]{64}$/u.test(firstControlledImage.digest) &&
    /^[0-9a-f]{64}$/u.test(firstControlledImage.id) &&
    imageBuildObservation.builds.solverBinarySha256 ===
      rootlessObservation.build.solverBinarySha256 &&
    imageBuildObservation.builds.matchesPriorRootlessObservationSolverBinary === true,
  "The controlled image timestamp, identity, or solver binary evidence drifted.",
);
requireValue(
  imageBuildObservation.sbom.status === "generated-external-unreviewed" &&
    imageBuildObservation.sbom.scanner.version === imageBuildPlan.sbom.scanner.version &&
    imageBuildObservation.sbom.scanner.manifestDigest ===
      imageBuildPlan.sbom.scanner.manifestDigest &&
    imageBuildObservation.sbom.scanner.imageId === imageBuildPlan.sbom.scanner.imageId &&
    imageBuildObservation.sbom.isolation.network === "none" &&
    imageBuildObservation.sbom.isolation.rootless === true &&
    imageBuildObservation.sbom.isolation.readOnlyRootFilesystem === true &&
    imageBuildObservation.sbom.isolation.capabilitiesDropped === "ALL" &&
    imageBuildObservation.sbom.isolation.noNewPrivileges === true &&
    imageBuildObservation.sbom.isolation.checkForAppUpdate === false,
  "The local-only SBOM scanner identity or isolation controls drifted.",
);
requireValue(
  imageBuildObservation.sbom.sourceArchive.configDigest ===
      "sha256:" + firstControlledImage.id &&
    imageBuildObservation.sbom.sourceArchive.configMatchesReproducibleImageId === true &&
    imageBuildObservation.sbom.sourceArchive.committed === false &&
    imageBuildObservation.sbom.sourceArchive.transmitted === false &&
    imageBuildObservation.sbom.document.format === "CycloneDX" &&
    imageBuildObservation.sbom.document.subjectManifestDigest ===
      imageBuildObservation.sbom.sourceArchive.manifestDigest &&
    imageBuildObservation.sbom.document.subjectMatchesArchiveManifest === true &&
    imageBuildObservation.sbom.document.packageComponents === 88 &&
    imageBuildObservation.sbom.document.packagesWithPurl === 88 &&
    imageBuildObservation.sbom.document.packagesWithLicenseEvidence === 88 &&
    imageBuildObservation.sbom.document.committed === false &&
    imageBuildObservation.sbom.licenseReviewComplete === false &&
    imageBuildObservation.sbom.distributionConclusionApproved === false,
  "The external SBOM facts must remain linked, complete, and unapproved.",
);
requireValue(
  imageBuildObservation.externalEvidence.absolutePathRecorded === false &&
    imageBuildObservation.externalEvidence.rawArtifactsCommitted === false &&
    imageBuildObservation.externalEvidence.files.length === 6 &&
    new Set(imageBuildObservation.externalEvidence.files.map(({ name }) => name)).size === 6 &&
    imageBuildObservation.externalEvidence.files.every(
      ({ name, bytes, sha256 }) =>
        !/[\\/]/u.test(name) &&
        Number.isInteger(bytes) &&
        bytes > 0 &&
        /^[0-9a-f]{64}$/u.test(sha256),
    ),
  "The external build evidence inventory is incomplete or unsafe.",
);
requireValue(
  imageBuildObservation.externalEvidence.collectorFiles.length === 3 &&
    new Set(imageBuildObservation.externalEvidence.collectorFiles.map(({ path }) => path)).size === 3,
  "The controlled build must identify its tool, library, and reviewed plan.",
);
for (const collectorFile of imageBuildObservation.externalEvidence.collectorFiles) {
  requireValue(
    !/^(?:[A-Za-z]:[\\/]|[\\/])/u.test(collectorFile.path) &&
      !collectorFile.path.split(/[\\/]+/u).includes(".."),
    "Controlled build collector path must stay inside OpenTCAD: " + collectorFile.path,
  );
  const bytes = await readFile(join(projectRoot, collectorFile.path));
  const actual = createHash("sha256").update(bytes).digest("hex");
  requireValue(
    actual === collectorFile.sha256,
    "Controlled build collector identity drifted: " + collectorFile.path,
  );
}
requireValue(
  imageBuildObservation.m0Result.reproducibleImageControlObserved === true &&
    imageBuildObservation.m0Result.localPodmanImageSbomGenerated === true &&
    imageBuildObservation.m0Result.base001Status === "pending" &&
    imageBuildObservation.m0Result.m0Exit === "not-met" &&
    baseline.solverExecutionBaseline.status === "pending" &&
    baseline.m0Exit.overall === "not-met",
  "The controlled image observation must not close BASE-001 or M0.",
);
requireValue(
  !JSON.stringify(imageBuildObservation).includes("/mnt/c/") &&
    !/[A-Za-z]:\\/.test(JSON.stringify(imageBuildObservation)),
  "The sanitized controlled image record must not contain an absolute host path.",
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
  ["docs/en/m0/base001-reference-observation.md", "docs/ko/m0/base001-reference-observation.md"],
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
    `M0 evidence check passed (${inventory.components.length} components, ${inventory.images.length} images, ${baseline.references.length} frozen references, 2 ineligible run observations, 1 non-baseline image build observation).`,
  );
}
