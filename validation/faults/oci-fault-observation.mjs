const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/u;
const ALLOWED_MODES = new Set([
  "completed",
  "nonzero-exit",
  "timed-out",
  "cancelled",
  "output-limit-exceeded",
]);
const ALLOWED_COMMANDS = new Map([
  ["/usr/bin/cat", [["/proc/self/status"]]],
  ["/usr/bin/touch", [["/tmp/opentcad-write-probe"]]],
  ["/usr/bin/false", [[]]],
  ["/usr/bin/sleep", [["30"]]],
  ["/usr/bin/yes", [["OpenTCAD fault output"]]],
  ["/usr/bin/true", [[]]],
]);

const BACKENDS = Object.freeze({
  docker: Object.freeze({
    version: ["version", "--format", "{{json .}}"],
    info: ["info", "--format", "{{json .}}"],
    pull: ["--pull", "never"],
    restart: ["--restart", "no"],
    inspect: (name) => ["container", "inspect", name],
    imageInspect: (reference) => ["image", "inspect", reference],
    orphanQuery: (filter) => ["ps", "--all", "--filter", filter, "--format", "{{json .}}"],
  }),
  podman: Object.freeze({
    version: ["version", "--format", "json"],
    info: ["info", "--format", "json"],
    pull: ["--pull=never"],
    restart: ["--restart=no"],
    inspect: (name) => ["container", "inspect", "--format", "json", name],
    imageInspect: (reference) => ["image", "inspect", "--format", "json", reference],
    orphanQuery: (filter) => ["ps", "--all", "--filter", filter, "--format", "json"],
  }),
});

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

function requireInteger(value, label, minimum, maximum) {
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new RangeError(`${label} must be an integer from ${minimum} through ${maximum}.`);
  }
  return value;
}

function assertExactCommand(command, label) {
  if (!Array.isArray(command) || command.some((part) => typeof part !== "string")) {
    throw new TypeError(`${label} must be an array of strings.`);
  }
  const [executable, ...args] = command;
  const allowedArguments = ALLOWED_COMMANDS.get(executable);
  if (!allowedArguments || !allowedArguments.some((allowed) => JSON.stringify(allowed) === JSON.stringify(args))) {
    throw new Error(`${label} is not in the reviewed command allowlist.`);
  }
}

function validateScenario(scenario, label) {
  requireObject(scenario, label);
  if (scenario.id !== undefined) requireString(scenario.id, `${label}.id`);
  if (!ALLOWED_MODES.has(scenario.mode)) throw new Error(`${label}.mode is not supported.`);
  assertExactCommand(scenario.command, `${label}.command`);
  if (["completed", "nonzero-exit"].includes(scenario.mode)) {
    requireInteger(scenario.expectedContainerExitCode, `${label}.expectedContainerExitCode`, 0, 255);
  } else if (scenario.expectedContainerExitCode !== undefined) {
    throw new Error(`${label} must not invent a container exit code for an injected fault.`);
  }
}

export function validateOciFaultPlan(plan) {
  requireObject(plan, "plan");
  if (plan.schemaVersion !== 1 || plan.milestone !== "M0") {
    throw new Error("Unsupported OCI fault observation plan schema or milestone.");
  }
  if (
    plan.observationId !== "M0-OCI-FAULT-001"
    || plan.classification !== "non-promoting-runtime-characterization"
    || plan.baselinePromotionAllowed !== false
    || plan.distributionAllowed !== false
  ) {
    throw new Error("The OCI fault observation must remain non-promoting and non-distributable.");
  }
  const issue = requireObject(plan.issueIntake, "issueIntake");
  if (issue.priority !== "P1" || issue.riskLevel !== "L3" || issue.domain !== "runtime/sandbox") {
    throw new Error("The OCI fault issue intake classification drifted.");
  }
  for (const field of ["problem", "reproduction", "expected"]) requireString(issue[field], `issueIntake.${field}`);
  for (const field of ["acceptance", "nonGoals"]) {
    if (!Array.isArray(issue[field]) || issue[field].length === 0) {
      throw new Error(`issueIntake.${field} must not be empty.`);
    }
  }

  const image = requireObject(plan.image, "image");
  for (const field of ["indexDigest", "platformManifestDigest", "rootFilesystemLayer"]) {
    if (!DIGEST_PATTERN.test(image[field])) throw new Error(`image.${field} must be a SHA-256 digest.`);
  }
  if (
    image.reference !== `docker.io/library/debian@${image.indexDigest}`
    || image.platform !== "linux/amd64"
    || image.pullPolicy !== "never"
    || image.distribution !== "local-observation-only-not-for-publication"
    || Number.isNaN(Date.parse(image.created))
  ) {
    throw new Error("The reviewed local-only OCI image identity drifted.");
  }

  const policy = requireObject(plan.policy, "policy");
  if (
    policy.network !== "none"
    || policy.capDrop !== "ALL"
    || policy.noNewPrivileges !== true
    || policy.readOnlyRootFilesystem !== true
    || policy.writableTemporaryFilesystems !== false
    || policy.user !== "65534:65534"
    || policy.pidsLimit !== 32
    || policy.memoryBytes !== 67_108_864
    || policy.cpus !== 0.5
    || policy.restart !== "no"
    || policy.stopTimeoutSeconds !== 1
    || !Array.isArray(policy.mounts)
    || policy.mounts.length !== 0
  ) {
    throw new Error("The reviewed OCI security or resource policy drifted.");
  }

  const limits = requireObject(plan.limits, "limits");
  for (const [field, minimum, maximum] of [
    ["probeTimeoutMs", 1, 60_000],
    ["probeOutputLimitBytes", 1, 4_194_304],
    ["normalOutputLimitBytes", 1, 1_048_576],
    ["faultTimeoutMs", 50, 5_000],
    ["cancelAfterMs", 50, 5_000],
    ["terminationGraceMs", 1, 5_000],
    ["outputBombLimitBytes", 1_024, 1_048_576],
  ]) {
    requireInteger(limits[field], `limits.${field}`, minimum, maximum);
  }

  if (!Array.isArray(plan.scenarios) || plan.scenarios.length !== 6) {
    throw new Error("The reviewed OCI fault matrix must contain six named scenarios.");
  }
  plan.scenarios.forEach((scenario, index) => validateScenario(scenario, `scenarios[${index}]`));
  const ids = plan.scenarios.map(({ id }) => id);
  if (new Set(ids).size !== ids.length) throw new Error("Scenario ids must be unique.");
  const expectedModes = ["completed", "nonzero-exit", "nonzero-exit", "timed-out", "cancelled", "output-limit-exceeded"];
  if (JSON.stringify(plan.scenarios.map(({ mode }) => mode)) !== JSON.stringify(expectedModes)) {
    throw new Error("The named OCI fault mode sequence drifted.");
  }

  const mixedLoop = requireObject(plan.mixedLoop, "mixedLoop");
  if (mixedLoop.count !== 20 || !Array.isArray(mixedLoop.pattern) || mixedLoop.pattern.length !== 3) {
    throw new Error("The mixed loop must retain 20 cases and a three-case pattern.");
  }
  mixedLoop.pattern.forEach((scenario, index) => validateScenario(scenario, `mixedLoop.pattern[${index}]`));
  if (JSON.stringify(mixedLoop.pattern.map(({ mode }) => mode)) !== JSON.stringify(["completed", "nonzero-exit", "cancelled"])) {
    throw new Error("The mixed loop must cover success, failure, and cancellation in order.");
  }

  const cleanup = requireObject(plan.cleanup, "cleanup");
  if (
    cleanup.observationLabel !== "org.opentcad.observation"
    || cleanup.managedLabel !== "org.opentcad.managed=true"
    || cleanup.removeByExactName !== true
    || cleanup.queryAfterEveryCase !== true
    || cleanup.expectedOrphans !== 0
  ) {
    throw new Error("The exact-name cleanup and orphan contract drifted.");
  }
  if (Object.values(requireObject(plan.rawEvidence, "rawEvidence")).some((value) => value !== false)) {
    throw new Error("Raw OCI fault evidence must remain external and uncommitted.");
  }
  return plan;
}

export function runtimeCommandArguments(runtime, kind, value) {
  const backend = BACKENDS[runtime];
  if (!backend) throw new Error(`Unsupported runtime: ${runtime}`);
  if (["version", "info"].includes(kind)) return [...backend[kind]];
  if (kind === "inspect") return backend.inspect(requireString(value, "container name"));
  if (kind === "image-inspect") return backend.imageInspect(requireString(value, "image reference"));
  if (kind === "start") return ["start", "--attach", requireString(value, "container name")];
  if (kind === "kill") return ["kill", requireString(value, "container name")];
  if (kind === "remove") return ["rm", "--force", requireString(value, "container name")];
  if (kind === "orphan-query") return backend.orphanQuery(requireString(value, "label filter"));
  throw new Error(`Unsupported runtime command kind: ${kind}`);
}

export function buildCreateArguments(runtime, plan, { name, caseId, observationValue, command }) {
  const backend = BACKENDS[runtime];
  if (!backend) throw new Error(`Unsupported runtime: ${runtime}`);
  requireString(name, "container name");
  requireString(caseId, "case id");
  requireString(observationValue, "observation label value");
  assertExactCommand(command, "container command");
  return [
    "create",
    ...backend.pull,
    "--platform",
    plan.image.platform,
    "--name",
    name,
    "--label",
    `${plan.cleanup.observationLabel}=${observationValue}`,
    "--label",
    plan.cleanup.managedLabel,
    "--label",
    `org.opentcad.case=${caseId}`,
    "--network",
    plan.policy.network,
    "--cap-drop",
    plan.policy.capDrop,
    "--security-opt",
    "no-new-privileges",
    "--read-only",
    ...(runtime === "podman" ? ["--read-only-tmpfs=false"] : []),
    "--user",
    plan.policy.user,
    "--pids-limit",
    String(plan.policy.pidsLimit),
    "--memory",
    String(plan.policy.memoryBytes),
    "--cpus",
    String(plan.policy.cpus),
    ...backend.restart,
    "--stop-timeout",
    String(plan.policy.stopTimeoutSeconds),
    plan.image.reference,
    ...command,
  ];
}

export function parseJson(bytes, label) {
  try {
    return JSON.parse(Buffer.isBuffer(bytes) ? bytes.toString("utf8") : String(bytes));
  } catch (error) {
    throw new Error(`${label} is not valid JSON: ${error.message}`);
  }
}

export function firstInspectRecord(bytes, label) {
  const parsed = parseJson(bytes, label);
  const record = Array.isArray(parsed) ? parsed[0] : parsed;
  if (!record || typeof record !== "object") throw new Error(`${label} returned no record.`);
  return record;
}

export function parseOrphanQuery(runtime, bytes) {
  const text = Buffer.isBuffer(bytes) ? bytes.toString("utf8").trim() : String(bytes).trim();
  if (text.length === 0) return [];
  if (runtime === "podman") {
    const parsed = parseJson(text, "Podman orphan query");
    if (!Array.isArray(parsed)) throw new Error("Podman orphan query must return an array.");
    return parsed;
  }
  return text.split(/\r?\n/u).map((line) => parseJson(line, "Docker orphan query line"));
}

export function evaluateContainerPolicy(runtime, inspect, plan) {
  const host = inspect.HostConfig ?? {};
  const config = inspect.Config ?? {};
  const createCommand = config.CreateCommand ?? [];
  const capDrop = host.CapDrop ?? [];
  const checks = {
    imageReference: config.Image === plan.image.reference,
    platformManifest:
      runtime === "docker"
        ? inspect.ImageManifestDescriptor?.digest === plan.image.platformManifestDigest
        : inspect.ImageDigest === plan.image.indexDigest,
    networkNone: host.NetworkMode === plan.policy.network,
    capabilitiesDropped:
      runtime === "docker"
        ? capDrop.includes("ALL")
        : createCommand.includes("--cap-drop") && createCommand.includes("ALL") && capDrop.length > 0,
    noNewPrivileges: (host.SecurityOpt ?? []).includes("no-new-privileges"),
    readOnlyRoot: host.ReadonlyRootfs === true,
    noImplicitWritableTemporaryFilesystems:
      runtime === "docker" ? true : createCommand.includes("--read-only-tmpfs=false"),
    fixedUser: config.User === plan.policy.user,
    pidsLimit: host.PidsLimit === plan.policy.pidsLimit,
    memory: host.Memory === plan.policy.memoryBytes,
    cpus: host.NanoCpus === plan.policy.cpus * 1_000_000_000,
    restartDisabled: host.RestartPolicy?.Name === plan.policy.restart,
    stopTimeout: config.StopTimeout === plan.policy.stopTimeoutSeconds,
    noMounts: (inspect.Mounts ?? []).length === 0 && (host.Binds ?? []).length === 0,
    notPrivileged: host.Privileged === false,
    notAutoRemoved: host.AutoRemove === false,
  };
  return { pass: Object.values(checks).every(Boolean), checks };
}

export function evaluateProcessStatus(bytes) {
  const text = Buffer.isBuffer(bytes) ? bytes.toString("utf8") : String(bytes);
  const fields = Object.fromEntries(
    text
      .split(/\r?\n/u)
      .map((line) => line.match(/^([^:]+):\s*(.*)$/u))
      .filter(Boolean)
      .map((match) => [match[1], match[2]]),
  );
  const checks = {
    effectiveCapabilitiesZero: fields.CapEff === "0000000000000000",
    noNewPrivileges: fields.NoNewPrivs === "1",
    uid65534: fields.Uid?.split(/\s+/u).every((value) => value === "65534") === true,
  };
  return { pass: Object.values(checks).every(Boolean), checks };
}

export function evaluateScenarioOutcome(scenario, startResult, inspect, plan) {
  const state = inspect.State ?? {};
  const checks = {};
  if (["completed", "nonzero-exit"].includes(scenario.mode)) {
    checks.containerStopped = state.Running === false;
    checks.containerExitCode = state.ExitCode === scenario.expectedContainerExitCode;
  } else {
    checks.supervisorClassification = startResult.classification === scenario.mode;
    checks.workerReset = startResult.worker?.reset === true;
  }
  if (scenario.mode === "output-limit-exceeded") {
    checks.outputTruncated = startResult.outputTruncated === true;
    checks.captureAtLimit = startResult.capturedOutputBytes === plan.limits.outputBombLimitBytes;
    checks.observedBeyondLimit = startResult.observedOutputBytes > plan.limits.outputBombLimitBytes;
  }
  return { pass: Object.values(checks).every(Boolean), checks };
}

export function normalizeRuntimeProfile(runtime, version, info) {
  if (runtime === "docker") {
    return {
      runtime,
      version: version.Server?.Version ?? info.ServerVersion ?? null,
      operatingSystem: version.Server?.Os ?? info.OSType ?? null,
      architecture: version.Server?.Arch === "x86_64" ? "amd64" : version.Server?.Arch ?? null,
      kernel: info.KernelVersion ?? version.Server?.KernelVersion ?? null,
      rootless: Array.isArray(info.SecurityOptions)
        && info.SecurityOptions.some((value) => String(value).toLowerCase().includes("rootless")),
      cgroupVersion: String(info.CgroupVersion ?? ""),
      cgroupManager: info.CgroupDriver ?? null,
    };
  }
  const host = info.host ?? info.Host ?? {};
  const security = host.security ?? host.Security ?? {};
  return {
    runtime,
    version: version.Client?.Version ?? version.client?.version ?? version.Version ?? null,
    operatingSystem: host.os ?? host.Os ?? null,
    architecture: ["x86_64", "x64"].includes(host.arch ?? host.Arch) ? "amd64" : host.arch ?? host.Arch ?? null,
    kernel: host.kernel ?? host.Kernel ?? null,
    rootless: security.rootless ?? security.Rootless ?? false,
    cgroupVersion: host.cgroupVersion ?? host.CgroupVersion ?? null,
    cgroupManager: host.cgroupManager ?? host.CgroupManager ?? null,
  };
}
