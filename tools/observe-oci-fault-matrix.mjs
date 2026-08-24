import { createHash } from "node:crypto";
import { lstat, mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import { arch, platform, release } from "node:os";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  buildCreateArguments,
  evaluateContainerPolicy,
  evaluateProcessStatus,
  evaluateScenarioOutcome,
  firstInspectRecord,
  normalizeRuntimeProfile,
  parseJson,
  parseOrphanQuery,
  runtimeCommandArguments,
  validateOciFaultPlan,
} from "../validation/faults/oci-fault-observation.mjs";
import { FaultPathSupervisor } from "../validation/faults/supervisor.mjs";

const REPOSITORY_ROOT = fileURLToPath(new URL("../", import.meta.url));
const REVIEWED_PLAN_PATH = resolve(REPOSITORY_ROOT, "validation/plans/m0-oci-fault-matrix.json");
const COLLECTOR_PATH = fileURLToPath(import.meta.url);
const OBSERVATION_LIBRARY_PATH = resolve(
  REPOSITORY_ROOT,
  "validation/faults/oci-fault-observation.mjs",
);
const SUPERVISOR_PATH = resolve(REPOSITORY_ROOT, "validation/faults/supervisor.mjs");
const WORKER_PATH = resolve(REPOSITORY_ROOT, "validation/faults/command-worker.mjs");
const WSL_DISTRIBUTION_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/u;
const INJECTED_FAULTS = new Set(["timed-out", "cancelled", "output-limit-exceeded"]);

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function slashPath(path) {
  return path.replaceAll("\\", "/");
}

function pathIsWithin(root, candidate) {
  const pathFromRoot = relative(root, candidate);
  return pathFromRoot === "" || (!pathFromRoot.startsWith("..") && !isAbsolute(pathFromRoot));
}

function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}

function parseArguments(argv) {
  const options = {};
  const valueOptions = new Set(["--plan", "--runtime", "--output", "--wsl-distribution", "--recorded-at"]);
  for (let index = 0; index < argv.length; index += 1) {
    const option = argv[index];
    if (option === "--help") return { help: true };
    if (!valueOptions.has(option)) throw new Error(`Unknown option: ${option}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`${option} requires a value.`);
    if (options[option] !== undefined) throw new Error(`${option} may be supplied only once.`);
    options[option] = value;
    index += 1;
  }
  for (const required of ["--plan", "--runtime", "--output"]) {
    if (!options[required]) throw new Error(`${required} is required.`);
  }
  if (!new Set(["docker", "podman"]).has(options["--runtime"])) {
    throw new Error("--runtime must be docker or podman.");
  }
  if (options["--runtime"] === "podman" && platform() === "win32") {
    const distribution = options["--wsl-distribution"];
    if (!distribution || !WSL_DISTRIBUTION_PATTERN.test(distribution)) {
      throw new Error("Windows Podman observations require a simple --wsl-distribution name.");
    }
  } else if (options["--wsl-distribution"] !== undefined) {
    throw new Error("--wsl-distribution is accepted only for Podman on Windows.");
  }
  if (options["--recorded-at"] && Number.isNaN(Date.parse(options["--recorded-at"]))) {
    throw new Error("--recorded-at must be an ISO-compatible timestamp.");
  }
  return {
    help: false,
    plan: resolve(options["--plan"]),
    runtime: options["--runtime"],
    output: resolve(options["--output"]),
    wslDistribution: options["--wsl-distribution"] ?? null,
    recordedAt: options["--recorded-at"] ?? new Date().toISOString(),
  };
}

function usage() {
  return [
    "Usage:",
    "  node tools/observe-oci-fault-matrix.mjs --plan validation/plans/m0-oci-fault-matrix.json --runtime docker --output <absolute-external-directory>",
    "  node tools/observe-oci-fault-matrix.mjs --plan validation/plans/m0-oci-fault-matrix.json --runtime podman --wsl-distribution Debian --output <absolute-external-directory>",
    "",
    "The output directory must not exist and must be outside the repository.",
  ].join("\n");
}

async function prepareExternalOutput(requestedPath) {
  requireValue(isAbsolute(requestedPath), "--output must be an absolute path.");
  const repository = await realpath(REPOSITORY_ROOT);
  const parent = await realpath(dirname(requestedPath));
  const output = resolve(parent, basename(requestedPath));
  requireValue(!pathIsWithin(repository, output), "Raw OCI evidence must remain outside the repository.");
  try {
    await lstat(output);
    throw new Error("The output directory already exists; evidence collection will not overwrite it.");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  await mkdir(output);
  await mkdir(join(output, "raw"));
  return output;
}

async function loadReviewedPlan(planPath) {
  const actual = await realpath(planPath);
  const expected = await realpath(REVIEWED_PLAN_PATH);
  requireValue(actual === expected, "Only the reviewed M0 OCI fault plan may be executed.");
  const bytes = await readFile(actual);
  return { bytes, plan: validateOciFaultPlan(parseJson(bytes, "OCI fault plan")) };
}

function runtimeTransport(runtime, wslDistribution) {
  if (runtime === "docker") {
    return {
      executable: platform() === "win32" ? "docker.exe" : "docker",
      prefix: [],
      summary: { launcher: "docker", runtimeExecutable: "docker", distribution: null },
    };
  }
  if (platform() === "win32") {
    return {
      executable: "wsl.exe",
      prefix: ["-d", wslDistribution, "--", "podman", "--cgroup-manager=cgroupfs"],
      summary: {
        launcher: "wsl",
        runtimeExecutable: "podman",
        distribution: wslDistribution,
      },
    };
  }
  return {
    executable: "podman",
    prefix: ["--cgroup-manager=cgroupfs"],
    summary: { launcher: "podman", runtimeExecutable: "podman", distribution: null },
  };
}

function commandSummary(result) {
  return {
    classification: result.classification,
    exitCode: result.exitCode,
    signal: result.signal,
    durationMs: result.durationMs,
    spawnError: result.spawnError,
    outputLimitBytes: result.outputLimitBytes,
    observedOutputBytes: result.observedOutputBytes,
    capturedOutputBytes: result.capturedOutputBytes,
    outputTruncated: result.outputTruncated,
    worker: result.worker,
  };
}

function makeArtifactWriter(output) {
  const artifacts = [];
  return {
    artifacts,
    async write(relativePath, bytesOrText) {
      const bytes = Buffer.isBuffer(bytesOrText) ? bytesOrText : Buffer.from(bytesOrText, "utf8");
      const target = resolve(output, relativePath);
      requireValue(pathIsWithin(output, target) && target !== output, "Evidence path escaped its output directory.");
      await mkdir(dirname(target), { recursive: true });
      await writeFile(target, bytes, { flag: "wx" });
      const artifact = {
        path: slashPath(relative(output, target)),
        bytes: bytes.byteLength,
        sha256: sha256(bytes),
      };
      artifacts.push(artifact);
      return artifact;
    },
  };
}

function safeStem(value) {
  return value.toLowerCase().replaceAll(/[^a-z0-9]+/gu, "-").replaceAll(/^-|-$/gu, "");
}

function assertCommandSucceeded(result, label) {
  requireValue(
    result.classification === "succeeded" && result.exitCode === 0,
    `${label} failed (${result.classification}, exit ${result.exitCode ?? "none"}).`,
  );
}

function imageIdentity(runtime, inspect, plan) {
  const repositoryDigests = inspect.RepoDigests ?? inspect.repoDigests ?? [];
  const rootLayers = inspect.RootFS?.Layers ?? inspect.Rootfs?.Layers ?? [];
  const digestCandidates = [
    inspect.Digest,
    inspect.digest,
    inspect.Descriptor?.digest,
    ...repositoryDigests.map((value) => String(value).split("@").at(-1)),
  ].filter(Boolean);
  const observedArchitecture = ["x86_64", "x64"].includes(inspect.Architecture)
    ? "amd64"
    : inspect.Architecture;
  const observedOperatingSystem = inspect.Os ?? inspect.OS;
  const checks = {
    indexDigestPresent: digestCandidates.includes(plan.image.indexDigest),
    rootFilesystemLayer: rootLayers.includes(plan.image.rootFilesystemLayer),
    created: Date.parse(inspect.Created) === Date.parse(plan.image.created),
    architecture: observedArchitecture === "amd64",
    operatingSystem: observedOperatingSystem === "linux",
  };
  return {
    pass: Object.values(checks).every(Boolean),
    runtime,
    reference: plan.image.reference,
    indexDigest: plan.image.indexDigest,
    platformManifestDigest: plan.image.platformManifestDigest,
    rootFilesystemLayer: plan.image.rootFilesystemLayer,
    created: plan.image.created,
    platform: plan.image.platform,
    pullPolicy: plan.image.pullPolicy,
    checks,
  };
}

async function repositoryFileEvidence(path) {
  const bytes = await readFile(path);
  return {
    path: slashPath(relative(REPOSITORY_ROOT, path)),
    bytes: bytes.byteLength,
    sha256: sha256(bytes),
  };
}

async function collect(options, output) {
  const { bytes: planBytes, plan } = await loadReviewedPlan(options.plan);
  const writer = makeArtifactWriter(output);
  const transport = runtimeTransport(options.runtime, options.wslDistribution);
  const supervisor = new FaultPathSupervisor({
    environmentAllowlist: ["DOCKER_CONTEXT", "DOCKER_HOST", "WSLENV", "WSL_INTEROP", "WSL_DISTRO_NAME"],
    startupTimeoutMs: 5_000,
    resetTimeoutMs: 2_000,
  });
  let commandNumber = 0;

  try {

  async function runRuntime(label, args, {
    timeoutMs = plan.limits.probeTimeoutMs,
    outputLimitBytes = plan.limits.probeOutputLimitBytes,
    signal,
  } = {}) {
    commandNumber += 1;
    const stem = `${String(commandNumber).padStart(3, "0")}-${safeStem(label)}`;
    const result = await supervisor.run(
      {
        executable: transport.executable,
        args: [...transport.prefix, ...args],
        timeoutMs,
        outputLimitBytes,
        terminationGraceMs: plan.limits.terminationGraceMs,
      },
      signal ? { signal } : undefined,
    );
    await writer.write(`raw/${stem}.stdout`, result.stdout);
    await writer.write(`raw/${stem}.stderr`, result.stderr);
    await writer.write(
      `raw/${stem}.json`,
      `${JSON.stringify({ label, runtimeArguments: args, result: commandSummary(result) }, null, 2)}\n`,
    );
    return result;
  }

  async function queryOrphans(observationValue, label) {
    const filter = `label=${plan.cleanup.observationLabel}=${observationValue}`;
    const result = await runRuntime(
      label,
      runtimeCommandArguments(options.runtime, "orphan-query", filter),
    );
    assertCommandSucceeded(result, label);
    return { result, containers: parseOrphanQuery(options.runtime, result.stdout) };
  }

  const observationValue = `${plan.observationId.toLowerCase()}-${options.runtime}`;
  const versionResult = await runRuntime(
    "runtime-version",
    runtimeCommandArguments(options.runtime, "version"),
  );
  assertCommandSucceeded(versionResult, "runtime version probe");
  const infoResult = await runRuntime(
    "runtime-info",
    runtimeCommandArguments(options.runtime, "info"),
  );
  assertCommandSucceeded(infoResult, "runtime info probe");
  const imageResult = await runRuntime(
    "image-inspect",
    runtimeCommandArguments(options.runtime, "image-inspect", plan.image.reference),
  );
  assertCommandSucceeded(imageResult, "local image inspection");

  const version = parseJson(versionResult.stdout, "runtime version");
  const info = parseJson(infoResult.stdout, "runtime info");
  const runtimeProfile = normalizeRuntimeProfile(options.runtime, version, info);
  requireValue(runtimeProfile.operatingSystem === "linux", "The observed runtime is not a Linux container runtime.");
  requireValue(runtimeProfile.architecture === "amd64", "The observed runtime is not amd64.");
  if (options.runtime === "podman") {
    requireValue(runtimeProfile.rootless === true, "The Podman observation must remain rootless.");
  }
  const inspectedImage = firstInspectRecord(imageResult.stdout, "local image inspection");
  const observedImage = imageIdentity(options.runtime, inspectedImage, plan);
  requireValue(observedImage.pass, "The local image does not match the reviewed immutable identity.");

  const initialOrphans = await queryOrphans(observationValue, "preflight-orphan-query");
  requireValue(
    initialOrphans.containers.length === 0,
    "Pre-existing containers carry this observation label; no automatic deletion was attempted.",
  );

  async function executeCase(scenario, ordinal, group) {
    const caseId = group === "named"
      ? scenario.id
      : `loop-${String(ordinal).padStart(2, "0")}-${scenario.mode}`;
    const containerName = `opentcad-m0-fault-${options.runtime}-${String(ordinal).padStart(3, "0")}`;
    const summary = {
      id: caseId,
      group,
      mode: scenario.mode,
      containerName,
      policy: null,
      processStatus: null,
      start: null,
      outcome: null,
      postFaultRecovery: null,
      cleanup: {
        exactNameRemoved: false,
        exactNameAbsent: false,
        labelledOrphans: null,
      },
      pass: false,
    };
    let created = false;
    let postStartInspect = null;
    let primaryError = null;
    let cleanupError = null;

    try {
      const createResult = await runRuntime(
        `${caseId}-create`,
        buildCreateArguments(options.runtime, plan, {
          name: containerName,
          caseId,
          observationValue,
          command: scenario.command,
        }),
      );
      assertCommandSucceeded(createResult, `${caseId} create`);
      created = true;

      const policyInspectResult = await runRuntime(
        `${caseId}-policy-inspect`,
        runtimeCommandArguments(options.runtime, "inspect", containerName),
      );
      assertCommandSucceeded(policyInspectResult, `${caseId} policy inspection`);
      const policyInspect = firstInspectRecord(policyInspectResult.stdout, `${caseId} policy inspection`);
      summary.policy = evaluateContainerPolicy(options.runtime, policyInspect, plan);
      requireValue(summary.policy.pass, `${caseId} did not retain the reviewed runtime policy.`);

      let startResult;
      if (scenario.mode === "cancelled") {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), plan.limits.cancelAfterMs);
        try {
          startResult = await runRuntime(
            `${caseId}-start`,
            runtimeCommandArguments(options.runtime, "start", containerName),
            {
              timeoutMs: plan.limits.probeTimeoutMs,
              outputLimitBytes: plan.limits.normalOutputLimitBytes,
              signal: controller.signal,
            },
          );
        } finally {
          clearTimeout(timer);
        }
      } else {
        startResult = await runRuntime(
          `${caseId}-start`,
          runtimeCommandArguments(options.runtime, "start", containerName),
          {
            timeoutMs: scenario.mode === "timed-out"
              ? plan.limits.faultTimeoutMs
              : plan.limits.probeTimeoutMs,
            outputLimitBytes: scenario.mode === "output-limit-exceeded"
              ? plan.limits.outputBombLimitBytes
              : plan.limits.normalOutputLimitBytes,
          },
        );
      }
      summary.start = commandSummary(startResult);

      const postStartInspectResult = await runRuntime(
        `${caseId}-post-start-inspect`,
        runtimeCommandArguments(options.runtime, "inspect", containerName),
      );
      assertCommandSucceeded(postStartInspectResult, `${caseId} post-start inspection`);
      postStartInspect = firstInspectRecord(
        postStartInspectResult.stdout,
        `${caseId} post-start inspection`,
      );
      summary.outcome = evaluateScenarioOutcome(scenario, startResult, postStartInspect, plan);
      const expectedClientClassification = scenario.mode === "completed"
        ? "succeeded"
        : scenario.mode === "nonzero-exit"
          ? "nonzero-exit"
          : scenario.mode;
      summary.outcome.checks.attachedClientClassification =
        startResult.classification === expectedClientClassification;
      summary.outcome.pass = Object.values(summary.outcome.checks).every(Boolean);

      if (scenario.id === "policy-process-status") {
        summary.processStatus = evaluateProcessStatus(startResult.stdout);
        requireValue(summary.processStatus.pass, `${caseId} process status did not retain the policy.`);
      }
      if (INJECTED_FAULTS.has(scenario.mode)) {
        summary.postFaultRecovery = {
          generationAdvanced:
            postStartInspectResult.worker.generation > startResult.worker.generation,
          workerPidChanged: postStartInspectResult.worker.pid !== startResult.worker.pid,
        };
        summary.postFaultRecovery.pass = Object.values(summary.postFaultRecovery).every(Boolean);
        requireValue(summary.postFaultRecovery.pass, `${caseId} did not recover through a new worker.`);
      }
      requireValue(summary.outcome.pass, `${caseId} terminal outcome did not match the plan.`);
    } catch (error) {
      primaryError = error;
    }

    if (created) {
      const cleanupErrors = [];
      if (!postStartInspect) {
        try {
          const recoveryInspect = await runRuntime(
            `${caseId}-cleanup-inspect`,
            runtimeCommandArguments(options.runtime, "inspect", containerName),
          );
          if (recoveryInspect.classification === "succeeded" && recoveryInspect.exitCode === 0) {
            postStartInspect = firstInspectRecord(recoveryInspect.stdout, `${caseId} cleanup inspection`);
          }
        } catch (error) {
          cleanupErrors.push(error);
        }
      }
      if (postStartInspect?.State?.Running === true) {
        try {
          const killResult = await runRuntime(
            `${caseId}-kill`,
            runtimeCommandArguments(options.runtime, "kill", containerName),
          );
          assertCommandSucceeded(killResult, `${caseId} kill`);
        } catch (error) {
          cleanupErrors.push(error);
        }
      }
      try {
        const removeResult = await runRuntime(
          `${caseId}-remove`,
          runtimeCommandArguments(options.runtime, "remove", containerName),
        );
        assertCommandSucceeded(removeResult, `${caseId} exact-name removal`);
        summary.cleanup.exactNameRemoved = true;
      } catch (error) {
        cleanupErrors.push(error);
      }
      try {
        const absentResult = await runRuntime(
          `${caseId}-confirm-absent`,
          runtimeCommandArguments(options.runtime, "inspect", containerName),
        );
        summary.cleanup.exactNameAbsent =
          absentResult.classification === "nonzero-exit" && absentResult.exitCode !== 0;
        requireValue(summary.cleanup.exactNameAbsent, `${caseId} still exists after removal.`);
      } catch (error) {
        cleanupErrors.push(error);
      }
      if (cleanupErrors.length > 0) {
        cleanupError = new Error(cleanupErrors.map((error) => error.message).join("; "));
      }
    }

    try {
      const orphanResult = await queryOrphans(observationValue, `${caseId}-orphan-query`);
      summary.cleanup.labelledOrphans = orphanResult.containers.length;
      requireValue(orphanResult.containers.length === 0, `${caseId} left labelled containers behind.`);
    } catch (error) {
      cleanupError ??= error;
    }

    summary.pass = primaryError === null
      && cleanupError === null
      && summary.policy?.pass === true
      && summary.outcome?.pass === true
      && summary.cleanup.exactNameRemoved
      && summary.cleanup.exactNameAbsent
      && summary.cleanup.labelledOrphans === 0;
    await writer.write(`raw/cases/${safeStem(caseId)}.json`, `${JSON.stringify(summary, null, 2)}\n`);
    if (!summary.pass) {
      const messages = [primaryError, cleanupError].filter(Boolean).map((error) => error.message);
      throw new Error(`${caseId} failed: ${messages.join("; ") || "one or more checks failed"}`);
    }
    return summary;
  }

  const namedScenarios = [];
  const mixedLoop = [];
  for (const [index, scenario] of plan.scenarios.entries()) {
      namedScenarios.push(await executeCase(scenario, index + 1, "named"));
    }
    for (let index = 0; index < plan.mixedLoop.count; index += 1) {
      const pattern = plan.mixedLoop.pattern[index % plan.mixedLoop.pattern.length];
      mixedLoop.push(await executeCase(pattern, plan.scenarios.length + index + 1, "mixed-loop"));
    }

    const finalOrphans = await queryOrphans(observationValue, "final-orphan-query");
    requireValue(finalOrphans.containers.length === 0, "The final orphan query was not empty.");
    const loopCounts = Object.fromEntries(
      [...new Set(plan.mixedLoop.pattern.map(({ mode }) => mode))].map((mode) => [
        mode,
        mixedLoop.filter((entry) => entry.mode === mode).length,
      ]),
    );
    const manifest = {
      schemaVersion: 1,
      milestone: "M0",
      observationId: plan.observationId,
      classification: plan.classification,
      recordedAt: options.recordedAt,
      status: "passed",
      runtime: options.runtime,
      hostCollector: {
        node: process.version,
        platform: platform(),
        architecture: arch(),
        release: release(),
      },
      transport: transport.summary,
      runtimeProfile,
      image: observedImage,
      policy: {
        declared: plan.policy,
        everyCasePassed: [...namedScenarios, ...mixedLoop].every((entry) => entry.policy.pass),
      },
      namedScenarios,
      mixedLoop: {
        count: mixedLoop.length,
        expectedCount: plan.mixedLoop.count,
        countsByMode: loopCounts,
        cases: mixedLoop,
        allPassed: mixedLoop.every((entry) => entry.pass),
      },
      cleanup: {
        initialLabelledContainers: initialOrphans.containers.length,
        queryAfterEveryCase: true,
        finalLabelledContainers: finalOrphans.containers.length,
        expectedOrphans: plan.cleanup.expectedOrphans,
        everyCaseExactNameRemoved: [...namedScenarios, ...mixedLoop].every(
          (entry) => entry.cleanup.exactNameRemoved && entry.cleanup.exactNameAbsent,
        ),
      },
      collectorFiles: await Promise.all([
        repositoryFileEvidence(COLLECTOR_PATH),
        repositoryFileEvidence(OBSERVATION_LIBRARY_PATH),
        repositoryFileEvidence(SUPERVISOR_PATH),
        repositoryFileEvidence(WORKER_PATH),
        Promise.resolve({
          path: slashPath(relative(REPOSITORY_ROOT, REVIEWED_PLAN_PATH)),
          bytes: planBytes.byteLength,
          sha256: sha256(planBytes),
        }),
      ]),
      rawEvidence: {
        location: "external-output-directory",
        committed: false,
        artifactCount: writer.artifacts.length,
        artifacts: writer.artifacts,
      },
      baselinePromotionAllowed: false,
      distributionAllowed: false,
    };
    const manifestBytes = Buffer.from(`${JSON.stringify(manifest, null, 2)}\n`, "utf8");
    await writeFile(join(output, "manifest.json"), manifestBytes, { flag: "wx" });
    return {
      runtime: options.runtime,
      status: manifest.status,
      output,
      manifestSha256: sha256(manifestBytes),
      namedScenarios: namedScenarios.length,
      mixedLoopCases: mixedLoop.length,
      finalLabelledContainers: finalOrphans.containers.length,
    };
  } finally {
    await supervisor.close();
  }
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  if (options.help) {
    console.log(usage());
    return;
  }
  const output = await prepareExternalOutput(options.output);
  try {
    const result = await collect(options, output);
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    const failure = {
      schemaVersion: 1,
      status: "failed",
      runtime: options.runtime,
      recordedAt: options.recordedAt,
      error: error instanceof Error ? error.message : String(error),
      rawEvidence: { location: "external-output-directory", committed: false },
      baselinePromotionAllowed: false,
      distributionAllowed: false,
    };
    try {
      await writeFile(join(output, "failure.json"), `${JSON.stringify(failure, null, 2)}\n`, {
        encoding: "utf8",
        flag: "wx",
      });
    } catch {
      // Preserve the primary collection error when failure metadata cannot be written.
    }
    throw error;
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
