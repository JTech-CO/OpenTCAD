function requireObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value;
}

function requireString(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${label} must be a non-empty string.`);
  }
  return value;
}

function requireSha256(value, label, prefix = false) {
  const pattern = prefix ? /^sha256:[0-9a-f]{64}$/u : /^[0-9a-f]{64}$/u;
  if (!pattern.test(value)) throw new TypeError(`${label} must be a SHA-256 digest.`);
  return value;
}

function requirePortableRelativePath(value, label) {
  requireString(value, label);
  if (/^(?:[A-Za-z]:[\\/]|[\\/])/u.test(value) || value.split(/[\\/]+/u).includes("..")) {
    throw new Error(`${label} must be a portable confined path.`);
  }
  return value;
}

function requireSafeUri(value, label) {
  requireString(value, label);
  const parsed = new URL(value);
  if (!["http:", "https:"].includes(parsed.protocol) || /['"|\s]/u.test(value)) {
    throw new Error(`${label} must be a safe HTTP(S) URI.`);
  }
  return value;
}

export function validateReferenceImageBuildPlan(plan) {
  requireObject(plan, "plan");
  if (plan.schemaVersion !== 1) throw new Error("Unsupported reference image build plan schema.");
  requireString(plan.planId, "plan.planId");
  if (plan.baselinePromotionAllowed !== false || plan.distributionAllowed !== false) {
    throw new Error("Reference build plans must forbid promotion and distribution.");
  }

  const reference = requireObject(plan.reference, "plan.reference");
  requireString(reference.repository, "plan.reference.repository");
  if (!/^[0-9a-f]{40}$/u.test(reference.commit)) {
    throw new Error("plan.reference.commit must be a full immutable commit id.");
  }
  requireSha256(reference.rawArchiveSha256, "plan.reference.rawArchiveSha256");
  if (!Number.isInteger(reference.commitTimestampEpoch) || reference.commitTimestampEpoch < 1) {
    throw new Error("plan.reference.commitTimestampEpoch must be a positive integer.");
  }
  const containerfile = requireObject(reference.containerfile, "plan.reference.containerfile");
  requirePortableRelativePath(containerfile.relativePath, "plan.reference.containerfile.relativePath");
  requireSha256(containerfile.sha256, "plan.reference.containerfile.sha256");

  const build = requireObject(plan.build, "plan.build");
  if (
    build.runtime !== "podman" ||
    build.format !== "oci" ||
    build.pullPolicy !== "never" ||
    build.noCache !== true ||
    build.cgroupManager !== "cgroupfs"
  ) {
    throw new Error("The build must retain the reviewed local-only Podman controls.");
  }
  if (build.timestampEpoch !== reference.commitTimestampEpoch) {
    throw new Error("The Podman timestamp must equal the frozen commit timestamp.");
  }
  if (!Number.isInteger(build.repeats) || build.repeats < 2) {
    throw new Error("The build plan must require at least two no-cache builds.");
  }
  const environment = requireObject(build.environment, "plan.build.environment");
  if (
    environment.sourceDateEpoch !== String(build.timestampEpoch) ||
    environment.lcAll !== "C" ||
    environment.tz !== "UTC"
  ) {
    throw new Error("The deterministic build environment is incomplete.");
  }

  if (!Array.isArray(build.baseImages) || build.baseImages.length !== 2) {
    throw new Error("Exactly two base image stages are required.");
  }
  const stages = new Set();
  for (const image of build.baseImages) {
    requireString(image.stage, "base image stage");
    requireString(image.sourceLine, `base image ${image.stage} sourceLine`);
    requireString(image.pinnedLine, `base image ${image.stage} pinnedLine`);
    requireSha256(image.manifestDigest, `base image ${image.stage} manifestDigest`, true);
    requireSha256(image.indexDigest, `base image ${image.stage} indexDigest`, true);
    if (!image.pinnedLine.includes(`@${image.manifestDigest}`)) {
      throw new Error(`Pinned line for ${image.stage} must use its amd64 manifest digest.`);
    }
    if (stages.has(image.stage)) throw new Error(`Duplicate base image stage: ${image.stage}.`);
    stages.add(image.stage);
  }
  if (!stages.has("builder") || !stages.has("runtime")) {
    throw new Error("Builder and runtime base image stages are required.");
  }

  if (!Array.isArray(build.aptSnapshots) || build.aptSnapshots.length !== 2) {
    throw new Error("Exactly two Debian snapshot rewrites are required.");
  }
  for (const snapshot of build.aptSnapshots) {
    requireSafeUri(snapshot.source, "apt snapshot source");
    requireSafeUri(snapshot.snapshot, "apt snapshot target");
    if (!snapshot.snapshot.includes("snapshot.debian.org/archive/")) {
      throw new Error("APT targets must use snapshot.debian.org archive paths.");
    }
  }
  if (build.checkValidUntil !== false) {
    throw new Error("Snapshot builds must explicitly disable Valid-Until checks.");
  }

  const sbom = requireObject(plan.sbom, "plan.sbom");
  const scanner = requireObject(sbom.scanner, "plan.sbom.scanner");
  requireString(scanner.name, "plan.sbom.scanner.name");
  requireString(scanner.version, "plan.sbom.scanner.version");
  requireString(scanner.reference, "plan.sbom.scanner.reference");
  requireSha256(scanner.manifestDigest, "plan.sbom.scanner.manifestDigest", true);
  requireSha256(scanner.imageId, "plan.sbom.scanner.imageId");
  if (!scanner.reference.includes(`@${scanner.manifestDigest}`)) {
    throw new Error("The SBOM scanner reference must use its manifest digest.");
  }
  if (
    sbom.source !== "oci-archive" ||
    sbom.format !== "cyclonedx-json" ||
    sbom.network !== "none" ||
    sbom.rawArchiveCommitted !== false ||
    sbom.rawSbomCommitted !== false
  ) {
    throw new Error("The local-only SBOM boundary is incomplete.");
  }

  return plan;
}

function replaceExactlyOnce(source, before, after, label) {
  const matches = source.split(before).length - 1;
  if (matches !== 1) throw new Error(`${label} must occur exactly once; found ${matches}.`);
  return source.replace(before, after);
}

export function renderPinnedContainerfile(source, plan) {
  validateReferenceImageBuildPlan(plan);
  if (typeof source !== "string" || source.length === 0) {
    throw new TypeError("Containerfile source must be a non-empty string.");
  }
  if (source.includes("\r")) throw new Error("Containerfile source must retain LF line endings.");

  let rendered = source;
  for (const image of plan.build.baseImages) {
    rendered = replaceExactlyOnce(
      rendered,
      image.sourceLine,
      image.pinnedLine,
      `${image.stage} base image line`,
    );
  }

  const builder = plan.build.baseImages.find(({ stage }) => stage === "builder");
  const snapshotCommands = plan.build.aptSnapshots.map(
    ({ source: current, snapshot }) =>
      `sed -i 's|URIs: ${current}$|URIs: ${snapshot}|' /etc/apt/sources.list.d/debian.sources`,
  );
  const deterministicBlock = [
    builder.pinnedLine,
    "",
    `ARG SOURCE_DATE_EPOCH=${plan.build.timestampEpoch}`,
    "ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH} LC_ALL=C TZ=UTC",
    "",
    `RUN ${snapshotCommands[0]} \\`,
    ` && ${snapshotCommands[1]} \\`,
    ` && printf 'Acquire::Check-Valid-Until "false";\\n' > /etc/apt/apt.conf.d/99opentcad-snapshot`,
  ].join("\n");

  return replaceExactlyOnce(
    rendered,
    builder.pinnedLine,
    deterministicBlock,
    "pinned builder image line",
  );
}
