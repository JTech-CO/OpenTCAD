import { readFile, mkdir, stat, writeFile } from "node:fs/promises";
import { basename, dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import {
  allowedEnvironment,
  collectFileEvidence,
  countLinePrefixes,
  evaluateLogPolicy,
  evaluateRequiredProfile,
  normalizeArchitecture,
  pathIsWithin,
  requireSafeRelativePath,
  runCapturedCommand,
  sha256Hex,
  summarizeArtifactRepeatability,
} from "../validation/baseline/observation.mjs";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const observerPath = fileURLToPath(import.meta.url);
const observationLibraryPath = fileURLToPath(
  new URL("../validation/baseline/observation.mjs", import.meta.url),
);

function usage() {
  return [
    "Usage:",
    "  node tools/observe-reference-run.mjs --plan <file> --reference-workspace <git-clone>",
    "    --source-root <raw-byte-tree> --output <external-directory>",
    "    --runtime <docker|podman> [--runtime-command <executable>] [--recorded-at <ISO>]",
    "",
    "The output directory must be outside the OpenTCAD repository. This command records",
    "an observation only; it never updates a baseline, fixture, expected value, or image lock.",
  ].join("\n");
}

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") return { help: true };
    if (!argument.startsWith("--")) throw new Error(`Unexpected argument: ${argument}`);
    const name = argument.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${argument}.`);
    if (options[name] !== undefined) throw new Error(`Duplicate option: ${argument}.`);
    options[name] = value;
    index += 1;
  }
  return options;
}

function requireOption(options, name) {
  const value = options[name];
  if (typeof value !== "string" || value.length === 0) throw new Error(`--${name} is required.`);
  return value;
}

function assertExternalPath(path, label) {
  if (pathIsWithin(projectRoot, path)) {
    throw new Error(`${label} must be outside the OpenTCAD repository.`);
  }
}

function requireObject(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError(`${label} must be an object.`);
  }
  return value;
}

function requireNonEmptyString(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${label} must be a non-empty string.`);
  }
  return value;
}

function requireStringArray(value, label) {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new TypeError(`${label} must be an array of strings.`);
  }
  return value;
}

function validatePlan(plan) {
  requireObject(plan, "plan");
  if (plan.schemaVersion !== 1) throw new Error("Unsupported observation plan schema.");
  requireNonEmptyString(plan.observationId, "observationId");
  requireNonEmptyString(plan.caseId, "caseId");
  if (plan.baselinePromotionAllowed !== false) {
    throw new Error("Observation plans must explicitly forbid automatic baseline promotion.");
  }
  const reference = requireObject(plan.reference, "reference");
  requireNonEmptyString(reference.repository, "reference.repository");
  if (!/^[0-9a-f]{40}$/u.test(reference.commit)) {
    throw new Error("reference.commit must be a full immutable commit id.");
  }
  const profile = requireObject(plan.requiredProfile, "requiredProfile");
  if (!["docker", "podman"].includes(profile.runtime)) {
    throw new Error("requiredProfile.runtime must be docker or podman.");
  }
  requireNonEmptyString(profile.operatingSystem, "requiredProfile.operatingSystem");
  requireNonEmptyString(profile.architecture, "requiredProfile.architecture");
  if (typeof profile.rootless !== "boolean") throw new Error("requiredProfile.rootless is required.");

  const image = requireObject(plan.image, "image");
  requireNonEmptyString(image.reference, "image.reference");
  requireNonEmptyString(image.distribution, "image.distribution");
  const invocation = requireObject(plan.invocation, "invocation");
  requireStringArray(invocation.args, "invocation.args");
  if (invocation.args[0] !== "run") throw new Error("The OCI invocation must use the run subcommand.");
  const args = invocation.args;
  if (!args.includes("--interactive")) throw new Error("The OCI invocation must keep stdin open.");
  if (!args.includes("--rm")) throw new Error("The OCI invocation must use --rm.");
  if (!args.includes("--read-only")) {
    throw new Error("The OCI invocation must use a read-only root filesystem.");
  }
  const requiredPairs = [
    ["--network", "none"],
    ["--cap-drop", "ALL"],
    ["--security-opt", "no-new-privileges"],
  ];
  for (const [flag, expected] of requiredPairs) {
    const index = args.indexOf(flag);
    if (index < 0 || args[index + 1] !== expected || args.indexOf(flag, index + 1) >= 0) {
      throw new Error(`The OCI invocation must use exactly one ${flag} ${expected}.`);
    }
  }
  for (const flag of ["--name", "--pids-limit", "--memory", "--cpus", "--tmpfs"]) {
    const index = args.indexOf(flag);
    if (index < 0 || !args[index + 1] || args[index + 1].startsWith("--")) {
      throw new Error(`The OCI invocation must declare ${flag}.`);
    }
    if (args.indexOf(flag, index + 1) >= 0) throw new Error(`Duplicate OCI flag: ${flag}.`);
  }
  const name = args[args.indexOf("--name") + 1];
  if (!name.includes("{runNumber}")) throw new Error("Container names must include {runNumber}.");
  const mountIndexes = args.flatMap((argument, index) => (argument === "--mount" ? [index] : []));
  if (
    mountIndexes.length !== 1 ||
    args[mountIndexes[0] + 1] !== "type=bind,source={runDir},target=/work"
  ) {
    throw new Error("The only host mount must bind {runDir} to /work.");
  }
  if (args.filter((argument) => argument === "{image}").length !== 1) {
    throw new Error("The OCI invocation must contain exactly one {image} token.");
  }
  const forbiddenArgumentPrefixes = [
    "--privileged",
    "--cap-add",
    "--device",
    "--entrypoint",
    "--env",
    "-e",
    "--volume",
    "-v",
    "--user",
    "--tty",
    "-t",
    "--pid",
    "--ipc",
    "--uts",
    "--cgroupns",
    "--runtime",
  ];
  const duplicateForms = [
    "--network=",
    "--cap-drop=",
    "--security-opt=",
    "--mount=",
    "--read-only=",
    "--rm=",
    "--interactive=",
    "--pids-limit=",
    "--memory=",
    "--cpus=",
    "--tmpfs=",
    "--name=",
  ];
  if (
    args.some((argument) =>
      forbiddenArgumentPrefixes.some(
        (prefix) => argument === prefix || argument.startsWith(`${prefix}=`),
      ),
    ) || args.some((argument) => duplicateForms.some((prefix) => argument.startsWith(prefix)))
  ) {
    throw new Error("The OCI invocation contains a forbidden or overriding runtime flag.");
  }
  if (!Number.isInteger(invocation.timeoutMs) || invocation.timeoutMs < 1) {
    throw new Error("invocation.timeoutMs must be a positive integer.");
  }
  if (!Number.isInteger(invocation.repeats) || invocation.repeats < 1 || invocation.repeats > 10) {
    throw new Error("invocation.repeats must be an integer from 1 through 10.");
  }
  requireNonEmptyString(invocation.stdinInputId, "invocation.stdinInputId");
  requireStringArray(invocation.environmentAllowlist ?? [], "invocation.environmentAllowlist");
  const logPolicy = requireObject(plan.logPolicy, "logPolicy");
  if (logPolicy.mode !== "fail-on-match") throw new Error("logPolicy.mode must be fail-on-match.");
  if (!Array.isArray(logPolicy.failurePatterns) || logPolicy.failurePatterns.length === 0) {
    throw new Error("logPolicy.failurePatterns are required.");
  }
  for (const pattern of logPolicy.failurePatterns) {
    requireNonEmptyString(pattern.id, "logPolicy pattern id");
    if (!["stdout", "stderr", "both"].includes(pattern.stream)) {
      throw new Error(`Unknown log stream for ${pattern.id}.`);
    }
    requireNonEmptyString(pattern.substring, `substring for ${pattern.id}`);
  }

  if (!Array.isArray(plan.inputs) || plan.inputs.length === 0) throw new Error("inputs are required.");
  if (!Array.isArray(plan.artifacts) || plan.artifacts.length === 0) {
    throw new Error("artifacts are required.");
  }
  for (const [label, descriptors] of [
    ["input", plan.inputs],
    ["artifact", plan.artifacts],
  ]) {
    for (const descriptor of descriptors) {
      requireNonEmptyString(descriptor.id, `${label}.id`);
      requireNonEmptyString(descriptor.kind, `${descriptor.id}.kind`);
      requireSafeRelativePath(descriptor.relativePath, `${descriptor.id}.relativePath`);
    }
    const ids = descriptors.map(({ id }) => id);
    if (new Set(ids).size !== ids.length) throw new Error(`${label} ids must be unique.`);
  }
  if (!plan.inputs.some(({ id }) => id === invocation.stdinInputId)) {
    throw new Error("invocation.stdinInputId does not identify a declared input.");
  }

  for (const metric of plan.metrics ?? []) {
    requireNonEmptyString(metric.id, "metric.id");
    if (metric.kind !== "line-prefix-counts") throw new Error(`Unknown metric kind: ${metric.kind}`);
    if (!plan.artifacts.some(({ id }) => id === metric.artifactId)) {
      throw new Error(`${metric.id} references an unknown artifact.`);
    }
    requireObject(metric.prefixes, `${metric.id}.prefixes`);
  }
  return plan;
}

async function ensureNewDirectory(path) {
  try {
    await stat(path);
    throw new Error(`Output already exists: ${path}`);
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  await mkdir(path, { recursive: true });
}

function filteredEnvironment(extraNames) {
  return allowedEnvironment(process.env, extraNames);
}

async function runProbe(executable, args, environment, timeoutMs = 30_000) {
  const result = await runCapturedCommand({ executable, args, timeoutMs, environment });
  if (result.classification !== "succeeded") {
    const detail = result.stderr.toString("utf8").trim().slice(0, 1000);
    throw new Error(`Probe failed: ${executable} ${args.join(" ")} (${detail || result.classification})`);
  }
  return result.stdout;
}

function parseJson(bytes, label) {
  try {
    return JSON.parse(bytes.toString("utf8"));
  } catch (error) {
    throw new Error(`${label} did not return JSON: ${error.message}`);
  }
}

function runtimeProbeArguments(runtime) {
  if (runtime === "docker") {
    return {
      version: ["version", "--format", "{{json .}}"],
      info: ["info", "--format", "{{json .}}"],
    };
  }
  return {
    version: ["version", "--format", "json"],
    info: ["info", "--format", "json"],
  };
}

function dockerRootless(info) {
  return Array.isArray(info.SecurityOptions) &&
    info.SecurityOptions.some((option) => String(option).toLowerCase().includes("rootless"));
}

function observedRuntimeProfile(runtime, version, info, image) {
  if (runtime === "docker") {
    return {
      runtime,
      runtimeVersion: version.Server?.Version ?? info.ServerVersion ?? null,
      operatingSystem: version.Server?.Os ?? info.OSType ?? image.Os ?? null,
      architecture: normalizeArchitecture(
        version.Server?.Arch ?? info.Architecture ?? image.Architecture ?? null,
      ),
      kernelVersion: info.KernelVersion ?? null,
      rootless: dockerRootless(info),
    };
  }

  const host = info.host ?? info.Host ?? {};
  const security = host.security ?? host.Security ?? {};
  const versionValue = version.Client?.Version ?? version.client?.version ?? version.Version ?? null;
  return {
    runtime,
    runtimeVersion: versionValue,
    operatingSystem: host.os ?? host.Os ?? image.Os ?? null,
    architecture: normalizeArchitecture(host.arch ?? host.Arch ?? image.Architecture ?? null),
    kernelVersion: host.kernel ?? host.Kernel ?? null,
    rootless: security.rootless ?? security.Rootless ?? false,
  };
}

function expandArgument(argument, replacements) {
  let expanded = argument;
  for (const [token, value] of Object.entries(replacements)) {
    expanded = expanded.replaceAll(`{${token}}`, value);
  }
  if (/\{[^}]+\}/u.test(expanded)) throw new Error(`Unknown invocation token in: ${argument}`);
  return expanded;
}

async function evidenceForBytes(path, bytes) {
  await writeFile(path, bytes);
  return {
    relativePath: relative(dirname(dirname(path)), path).split(sep).join("/"),
    bytes: bytes.byteLength,
    sha256: sha256Hex(bytes),
  };
}

function safeImageRecord(image, reference, distribution) {
  return {
    reference,
    distribution,
    id: image.Id ?? image.ID ?? null,
    repositoryDigests: [...(image.RepoDigests ?? image.RepositoryDigests ?? [])].sort(),
    operatingSystem: image.Os ?? image.OS ?? null,
    architecture: normalizeArchitecture(image.Architecture ?? image.Arch ?? null),
    rootFilesystemLayers: image.RootFS?.Layers?.length ?? null,
  };
}

function summarizeMetricRepeatability(runs, metricDescriptors) {
  return metricDescriptors.map(({ id }) => {
    const values = runs.map((run) => run.metrics.find((metric) => metric.id === id)?.values ?? null);
    const serialized = values.map((value) => JSON.stringify(value));
    return {
      metricId: id,
      observedRuns: values.filter((value) => value !== null).length,
      expectedRuns: runs.length,
      exactlyRepeatable: values.every((value) => value !== null) && new Set(serialized).size === 1,
      values,
    };
  });
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  if (options.help) {
    console.log(usage());
    return;
  }

  const planPath = resolve(requireOption(options, "plan"));
  const plansRoot = resolve(projectRoot, "validation", "plans");
  if (!pathIsWithin(plansRoot, planPath)) {
    throw new Error("--plan must identify a reviewed file inside validation/plans.");
  }
  const referenceWorkspace = resolve(requireOption(options, "reference-workspace"));
  const sourceRoot = resolve(options["source-root"] ?? referenceWorkspace);
  const outputDirectory = resolve(requireOption(options, "output"));
  const runtime = requireOption(options, "runtime");
  if (!["docker", "podman"].includes(runtime)) throw new Error("--runtime must be docker or podman.");
  const runtimeCommand = options["runtime-command"] ?? runtime;
  const runtimeExecutableName = basename(runtimeCommand).toLowerCase().replace(/\.exe$/u, "");
  if (runtimeExecutableName !== runtime) {
    throw new Error("--runtime-command must name the selected Docker or Podman executable.");
  }
  const recordedAt = options["recorded-at"] ?? new Date().toISOString();
  if (Number.isNaN(Date.parse(recordedAt))) throw new Error("--recorded-at must be an ISO date-time.");

  assertExternalPath(referenceWorkspace, "Reference workspace");
  assertExternalPath(sourceRoot, "Source root");
  assertExternalPath(outputDirectory, "Output directory");
  if (pathIsWithin(outputDirectory, referenceWorkspace) || pathIsWithin(referenceWorkspace, outputDirectory)) {
    throw new Error("Output and reference workspace must not contain one another.");
  }

  const planBytes = await readFile(planPath);
  const plan = validatePlan(JSON.parse(planBytes.toString("utf8")));
  const environment = filteredEnvironment(plan.invocation.environmentAllowlist ?? []);
  const gitHead = (
    await runProbe("git", ["-C", referenceWorkspace, "rev-parse", "HEAD"], environment)
  )
    .toString("utf8")
    .trim();
  if (gitHead !== plan.reference.commit) {
    throw new Error(`Reference commit mismatch: expected ${plan.reference.commit}, found ${gitHead}.`);
  }
  const gitStatus = await runProbe(
    "git",
    ["-C", referenceWorkspace, "status", "--porcelain=v1"],
    environment,
  );

  const inputs = [];
  const inputBytes = new Map();
  for (const descriptor of plan.inputs) {
    const relativePath = requireSafeRelativePath(descriptor.relativePath, `${descriptor.id}.relativePath`);
    const sourcePath = resolve(sourceRoot, relativePath);
    if (!pathIsWithin(sourceRoot, sourcePath)) throw new Error(`${descriptor.id} escapes source root.`);
    const bytes = await readFile(sourcePath);
    const expectedBlob = (
      await runProbe(
        "git",
        ["-C", referenceWorkspace, "rev-parse", `${plan.reference.commit}:${relativePath}`],
        environment,
      )
    )
      .toString("utf8")
      .trim();
    const actualBlob = (
      await runProbe("git", ["hash-object", "--no-filters", sourcePath], environment)
    )
      .toString("utf8")
      .trim();
    if (expectedBlob !== actualBlob) {
      throw new Error(`${descriptor.id} bytes do not match the frozen Git blob.`);
    }
    inputBytes.set(descriptor.id, bytes);
    inputs.push({
      id: descriptor.id,
      kind: descriptor.kind,
      relativePath,
      bytes: bytes.byteLength,
      sha256: sha256Hex(bytes),
      gitBlob: actualBlob,
      matchesFrozenCommit: true,
    });
  }

  const probeArgs = runtimeProbeArguments(runtime);
  const runtimeVersionRaw = await runProbe(runtimeCommand, probeArgs.version, environment);
  const runtimeInfoRaw = await runProbe(runtimeCommand, probeArgs.info, environment);
  const imageInspectRaw = await runProbe(
    runtimeCommand,
    ["image", "inspect", plan.image.reference],
    environment,
  );
  const versionData = parseJson(runtimeVersionRaw, "Runtime version probe");
  const infoData = parseJson(runtimeInfoRaw, "Runtime info probe");
  const imageInspectData = parseJson(imageInspectRaw, "Image inspection probe");
  const imageData = Array.isArray(imageInspectData) ? imageInspectData[0] : imageInspectData;
  if (!imageData) throw new Error("Image inspection returned no image.");
  const imageIdentity = imageData.Id ?? imageData.ID;
  if (typeof imageIdentity !== "string" || imageIdentity.length === 0) {
    throw new Error("Image inspection returned no immutable image identity.");
  }
  const observedProfile = observedRuntimeProfile(runtime, versionData, infoData, imageData);
  const profileEvaluation = evaluateRequiredProfile(plan.requiredProfile, observedProfile);

  await ensureNewDirectory(outputDirectory);
  const probesDirectory = resolve(outputDirectory, "probes");
  await mkdir(probesDirectory);
  const probes = {
    runtimeVersion: await evidenceForBytes(
      resolve(probesDirectory, "runtime-version.json"),
      runtimeVersionRaw,
    ),
    runtimeInfo: await evidenceForBytes(resolve(probesDirectory, "runtime-info.json"), runtimeInfoRaw),
    imageInspect: await evidenceForBytes(
      resolve(probesDirectory, "image-inspect.json"),
      imageInspectRaw,
    ),
  };

  const stdinBytes = inputBytes.get(plan.invocation.stdinInputId);
  const runs = [];
  for (let index = 0; index < plan.invocation.repeats; index += 1) {
    const runNumber = String(index + 1).padStart(2, "0");
    const runDirectory = resolve(outputDirectory, `run-${runNumber}`);
    await mkdir(runDirectory);
    const replacements = {
      image: imageIdentity,
      runDir: runDirectory,
      runNumber,
      observationId: plan.observationId,
    };
    const args = plan.invocation.args.map((argument) => expandArgument(argument, replacements));
    const commandResult = await runCapturedCommand({
      executable: runtimeCommand,
      args,
      cwd: sourceRoot,
      stdin: stdinBytes,
      timeoutMs: plan.invocation.timeoutMs,
      environment,
    });
    const logEvaluation = evaluateLogPolicy(
      commandResult.stdout,
      commandResult.stderr,
      plan.logPolicy,
    );
    const stdout = await evidenceForBytes(resolve(runDirectory, "stdout.bin"), commandResult.stdout);
    const stderr = await evidenceForBytes(resolve(runDirectory, "stderr.bin"), commandResult.stderr);

    let cleanup = null;
    if (commandResult.timedOut) {
      const nameIndex = args.indexOf("--name");
      if (nameIndex >= 0 && args[nameIndex + 1]) {
        const cleanupResult = await runCapturedCommand({
          executable: runtimeCommand,
          args: ["rm", "--force", args[nameIndex + 1]],
          timeoutMs: 30_000,
          environment,
        });
        cleanup = {
          classification: cleanupResult.classification,
          exitCode: cleanupResult.exitCode,
          stdout: await evidenceForBytes(
            resolve(runDirectory, "cleanup.stdout.bin"),
            cleanupResult.stdout,
          ),
          stderr: await evidenceForBytes(
            resolve(runDirectory, "cleanup.stderr.bin"),
            cleanupResult.stderr,
          ),
        };
      }
    }

    const artifacts = [];
    for (const descriptor of plan.artifacts) {
      artifacts.push(await collectFileEvidence(runDirectory, descriptor));
    }
    const metrics = [];
    for (const descriptor of plan.metrics ?? []) {
      const artifact = artifacts.find(({ id }) => id === descriptor.artifactId);
      if (!artifact?.present) {
        metrics.push({ id: descriptor.id, kind: descriptor.kind, artifactId: descriptor.artifactId, values: null });
        continue;
      }
      const artifactBytes = await readFile(resolve(runDirectory, artifact.relativePath));
      metrics.push({
        id: descriptor.id,
        kind: descriptor.kind,
        artifactId: descriptor.artifactId,
        values: countLinePrefixes(artifactBytes, descriptor.prefixes),
      });
    }
    const requiredArtifactsPresent = artifacts
      .filter(({ required }) => required)
      .every(({ present }) => present);
    runs.push({
      runNumber: index + 1,
      status:
        commandResult.classification === "succeeded" && logEvaluation.pass && requiredArtifactsPresent
          ? "completed"
          : "failed",
      command: {
        classification: commandResult.classification,
        exitCode: commandResult.exitCode,
        signal: commandResult.signal,
        timedOut: commandResult.timedOut,
        durationMs: commandResult.durationMs,
        spawnError: commandResult.spawnError,
        logPolicy: logEvaluation,
        stdout,
        stderr,
      },
      cleanup,
      artifacts,
      metrics,
    });
  }

  const allRunsCompleted = runs.every(({ status }) => status === "completed");
  const artifactRepeatability = summarizeArtifactRepeatability(runs, plan.artifacts);
  const metricRepeatability = summarizeMetricRepeatability(runs, plan.metrics ?? []);
  const requiredArtifactsRepeatable = artifactRepeatability
    .filter(({ required }) => required)
    .every(({ exactlyRepeatable }) => exactlyRepeatable);
  const baselineEligibility =
    allRunsCompleted && requiredArtifactsRepeatable && profileEvaluation.meetsRequiredProfile
      ? "review-required"
      : "ineligible";
  const outstandingGates = [
    "qualified solver and patch license review",
    "immutable image manifest digest and SBOM review",
    "semiconductor numerical review and explicit maintainer approval",
  ];
  if (runs.some(({ command }) => !command.logPolicy.pass)) {
    outstandingGates.unshift("one or more runs contain declared log failures");
  }
  if (!profileEvaluation.meetsRequiredProfile) {
    outstandingGates.unshift(
      `required environment mismatch: ${profileEvaluation.mismatches.join(", ")}`,
    );
  }

  const manifest = {
    schemaVersion: 1,
    milestone: "M0",
    observationId: plan.observationId,
    caseId: plan.caseId,
    recordedAt,
    status: allRunsCompleted ? "completed" : "failed",
    classification: plan.classification,
    baselinePromotionAllowed: false,
    baselineEligibility,
    collector: {
      interfaceVersion: 1,
      files: [
        {
          path: relative(projectRoot, observerPath).split(sep).join("/"),
          sha256: sha256Hex(await readFile(observerPath)),
        },
        {
          path: relative(projectRoot, observationLibraryPath).split(sep).join("/"),
          sha256: sha256Hex(await readFile(observationLibraryPath)),
        },
        {
          path: relative(projectRoot, planPath).split(sep).join("/"),
          sha256: sha256Hex(planBytes),
        },
      ],
    },
    reference: {
      repository: plan.reference.repository,
      commit: plan.reference.commit,
      verifiedHead: gitHead,
      workingTreeClean: gitStatus.byteLength === 0,
      sourceBytesMatchFrozenGitBlobs: inputs.every(({ matchesFrozenCommit }) => matchesFrozenCommit),
    },
    hostCollector: {
      platform: process.platform,
      architecture: normalizeArchitecture(process.arch),
      nodeVersion: process.version,
    },
    requiredProfile: plan.requiredProfile,
    observedProfile,
    profileEvaluation,
    image: safeImageRecord(imageData, plan.image.reference, plan.image.distribution),
    commandContract: {
      runtime,
      runtimeCommand: isAbsolute(runtimeCommand) ? "<absolute-runtime-command>" : runtimeCommand,
      args: plan.invocation.args,
      stdinInputId: plan.invocation.stdinInputId,
      timeoutMs: plan.invocation.timeoutMs,
      repeats: plan.invocation.repeats,
      environmentAllowlist: Object.keys(environment).sort((left, right) => left.localeCompare(right)),
    },
    inputs,
    probes,
    runs,
    repeatability: {
      artifacts: artifactRepeatability,
      metrics: metricRepeatability,
    },
    outstandingGates,
  };

  const manifestPath = resolve(outputDirectory, "manifest.json");
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.log(`Observation manifest: ${manifestPath}`);
  console.log(`Status: ${manifest.status}`);
  console.log(`Baseline eligibility: ${manifest.baselineEligibility}`);
  if (!allRunsCompleted) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.stack ?? error.message);
  console.error(usage());
  process.exitCode = 1;
});
