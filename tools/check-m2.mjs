import { createHash } from "node:crypto";
import { access, readFile } from "node:fs/promises";
import { isAbsolute, join, normalize, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const errors = [];

const expectedProtocolOperations = [
  "probe",
  "inspect_image",
  "ensure_image",
  "create_volume",
  "stage_inputs",
  "create_container",
  "start",
  "wait",
  "kill",
  "collect_artifacts",
  "remove_container",
  "remove_volume",
  "list_managed",
];

const expectedCapabilityVocabulary = [
  "image_inspect",
  "image_pull",
  "image_digest",
  "managed_volumes",
  "validated_input_transfer",
  "container_lifecycle",
  "bounded_output",
  "cpu_limit",
  "memory_limit",
  "pids_limit",
  "timeout",
  "network_none",
  "cap_drop_all",
  "no_new_privileges",
  "read_only_root",
  "writable_tmpfs_control",
  "fixed_non_root_user",
  "labels",
  "orphan_query",
  "validated_artifact_transfer",
];

const expectedRequiredCapabilities = expectedCapabilityVocabulary.filter(
  (capability) => capability !== "image_pull",
);

const expectedErrorCodes = [
  "runtime-unavailable",
  "capability-missing",
  "image-not-approved",
  "image-identity-mismatch",
  "invalid-spec",
  "volume-not-found",
  "container-not-found",
  "invalid-state",
  "stale-state",
  "start-failed",
  "wait-failed",
  "kill-failed",
  "cleanup-failed",
  "artifact-rejected",
];

const expectedSourceFiles = [
  "backend/app/runtime/errors.py",
  "backend/app/runtime/models.py",
  "backend/app/runtime/policy.py",
  "backend/app/runtime/protocol.py",
  "backend/app/runtime/mock_backend.py",
  "backend/pyproject.toml",
  "backend/tests/runtime/support.py",
  "backend/tests/runtime/test_policy.py",
  "backend/tests/runtime/test_mock_backend.py",
  "tools/check-m2.mjs",
  "tools/run-python-tests.mjs",
  "docs/en/m2/README.md",
  "docs/en/m2/runtime-backend-adr.md",
  "docs/en/m2/broker-threat-model.md",
  "docs/ko/m2/README.md",
  "docs/ko/m2/runtime-backend-adr.md",
  "docs/ko/m2/broker-threat-model.md",
  "docs/CODEMAPS/README.md",
  "docs/CODEMAPS/backend.md",
];

function requireValue(condition, message) {
  if (!condition) errors.push(message);
}

function sameArray(actual, expected) {
  return Array.isArray(actual)
    && actual.length === expected.length
    && actual.every((value, index) => value === expected[index]);
}

function isRepositoryPath(path) {
  if (typeof path !== "string" || path.length === 0 || isAbsolute(path)) return false;
  const resolved = normalize(join(root, path));
  const fromRoot = relative(root, resolved);
  return fromRoot !== "" && !fromRoot.startsWith("..") && !isAbsolute(fromRoot);
}

async function readJson(path) {
  return JSON.parse(await readFile(join(root, path), "utf8"));
}

async function sha256AndBytes(path) {
  const bytes = await readFile(join(root, path));
  return {
    bytes: bytes.byteLength,
    sha256: createHash("sha256").update(bytes).digest("hex"),
  };
}

async function exists(path) {
  try {
    await access(join(root, path));
    return true;
  } catch {
    return false;
  }
}

const [manifest, m1, oci, packageJson, pyproject, protocol, models, policy, errorsSource] =
  await Promise.all([
    readJson("validation/manifests/m2-runtime-foundation.json"),
    readJson("validation/manifests/m1-foundation.json"),
    readJson("m0/OCI_FAULT_MATRIX_OBSERVATION.json"),
    readJson("package.json"),
    readFile(join(root, "backend/pyproject.toml"), "utf8"),
    readFile(join(root, "backend/app/runtime/protocol.py"), "utf8"),
    readFile(join(root, "backend/app/runtime/models.py"), "utf8"),
    readFile(join(root, "backend/app/runtime/policy.py"), "utf8"),
    readFile(join(root, "backend/app/runtime/errors.py"), "utf8"),
  ]);

requireValue(manifest.schemaVersion === 1, "Unsupported M2 manifest schema.");
requireValue(manifest.milestone === "M2", "Manifest milestone must be M2.");
requireValue(manifest.status === "gated-active", "M2 must remain gated-active.");
requireValue(
  manifest.scope === "engine-independent-contract-only",
  "M2 scope must remain engine-independent-contract-only.",
);
requireValue(manifest.entryConditions.m1CorpusGreen === false, "M1 corpus is not green.");
requireValue(
  manifest.entryConditions.runtimeInterfaceAdr.status === "proposed",
  "Runtime ADR must remain proposed until approval.",
);
requireValue(
  manifest.entryConditions.brokerThreatModel.status === "draft",
  "Broker threat model must remain draft until approval.",
);
requireValue(manifest.entryConditions.overall === "not-met", "M2 entry must remain not-met.");
requireValue(manifest.exitCriteria.overall === "not-met", "M2 exit must remain not-met.");
requireValue(manifest.productExecutionAllowed === false, "Product execution must remain disabled.");
requireValue(manifest.distributionAllowed === false, "Solver distribution must remain disabled.");

for (const key of [
  "productRuntimeSocketAccess",
  "productAdapterImplemented",
  "brokerServiceImplemented",
  "runtimeDetectionImplemented",
  "workerIntegrationImplemented",
  "solverExecutionImplemented",
  "rawCommandAccepted",
  "hostPathAccepted",
  "arbitraryMountAccepted",
]) {
  requireValue(manifest.securityBoundary[key] === false, `${key} must remain false.`);
}

requireValue(
  sameArray(manifest.contract.protocolOperations, expectedProtocolOperations),
  "RuntimeBackend operation list drifted.",
);
requireValue(
  sameArray(manifest.contract.capabilityVocabulary, expectedCapabilityVocabulary),
  "Runtime capability vocabulary drifted.",
);
requireValue(
  sameArray(manifest.contract.requiredCapabilities, expectedRequiredCapabilities),
  "Required runtime capability list drifted.",
);
requireValue(
  sameArray(manifest.contract.stableErrorCodes, expectedErrorCodes),
  "Stable runtime error list drifted.",
);

for (const operation of expectedProtocolOperations) {
  requireValue(
    protocol.includes(`async def ${operation}(`),
    `RuntimeBackend protocol is missing ${operation}.`,
  );
}
for (const capability of expectedCapabilityVocabulary) {
  requireValue(models.includes(`    "${capability}",`), `Model is missing capability ${capability}.`);
}
for (const capability of expectedRequiredCapabilities) {
  requireValue(policy.includes(`    "${capability}",`), `Policy is missing capability ${capability}.`);
}
for (const code of expectedErrorCodes) {
  requireValue(errorsSource.includes(`= "${code}"`), `Error source is missing ${code}.`);
}

requireValue(m1.status === "gated-active", "M1 status unexpectedly changed.");
requireValue(m1.exitCriteria.overall === "not-met", "M1 exit unexpectedly changed.");
requireValue(
  oci.m0Result.productRuntimeAdapterQualified === false,
  "Non-promoting OCI evidence cannot qualify a product adapter.",
);
requireValue(oci.scope.usesProductRuntimeAdapter === false, "OCI evidence unexpectedly used an adapter.");
requireValue(oci.scope.usesSolver === false, "OCI fault evidence unexpectedly used a solver.");

const workItems = new Map(manifest.workItems.map((item) => [item.id, item.status]));
const expectedWorkItems = new Map([
  ["RUN-001", "observed-nonpromoting"],
  ["RUN-002", "foundation-tested"],
  ["RUN-003", "foundation-tested"],
  ["RUN-004", "blocked-entry-gate"],
  ["RUN-005", "blocked-entry-gate"],
  ["RUN-006", "not-started"],
  ["RUN-007", "mock-only"],
]);
requireValue(workItems.size === expectedWorkItems.size, "M2 work item set drifted.");
for (const [id, status] of expectedWorkItems) {
  requireValue(workItems.get(id) === status, `${id} must remain ${status}.`);
}

requireValue(manifest.testContract.command === "npm run test:runtime", "Runtime test command drifted.");
requireValue(manifest.testContract.testCount === 15, "Runtime test count must be 15.");
requireValue(manifest.testContract.usesRuntime === false, "Contract tests must not use a runtime.");
requireValue(manifest.testContract.usesSolver === false, "Contract tests must not use a solver.");
requireValue(manifest.testContract.loopCases === 20, "Cleanup loop must contain 20 cases.");
requireValue(
  manifest.testContract.finalManagedObjects === 0,
  "Cleanup contract must end with zero managed objects.",
);

const scripts = packageJson.scripts ?? {};
requireValue(scripts["test:runtime"] === "node tools/run-python-tests.mjs", "test:runtime script drifted.");
requireValue(scripts["check:m2"] === "node tools/check-m2.mjs", "check:m2 script drifted.");
requireValue(scripts.test?.includes("npm run test:runtime"), "Default test must run runtime tests.");
requireValue(scripts.check?.includes("npm run check:m2"), "Default check must run the M2 verifier.");
requireValue(pyproject.includes('requires-python = ">=3.12,<3.15"'), "Python support range drifted.");
requireValue((await readFile(join(root, ".github/workflows/ci.yml"), "utf8")).includes("actions/setup-python@v7"), "CI must provision Python 3.12.");
requireValue((await readFile(join(root, ".github/workflows/pages.yml"), "utf8")).includes("actions/setup-python@v7"), "Pages must provision Python 3.12.");

const actualSourcePaths = manifest.sourceFiles.map((entry) => entry.path);
requireValue(sameArray(actualSourcePaths, expectedSourceFiles), "Frozen M2 source file list drifted.");
for (const entry of manifest.sourceFiles) {
  if (!isRepositoryPath(entry.path)) {
    errors.push(`Invalid source path: ${entry.path}`);
    continue;
  }
  try {
    const actual = await sha256AndBytes(entry.path);
    requireValue(actual.bytes === entry.bytes, `${entry.path} byte length drifted.`);
    requireValue(actual.sha256 === entry.sha256, `${entry.path} SHA-256 drifted.`);
  } catch {
    errors.push(`Missing frozen M2 source: ${entry.path}`);
  }
}

for (const path of [
  "backend/app/runtime/docker_backend.py",
  "backend/app/runtime/podman_backend.py",
  "backend/app/runtime/detection.py",
  "backend/app/broker",
  "backend/app/worker",
]) {
  requireValue(!(await exists(path)), `Blocked product implementation exists: ${path}`);
}

const implementation = [protocol, models, policy, errorsSource, await readFile(join(root, "backend/app/runtime/mock_backend.py"), "utf8")].join("\n");
for (const [label, pattern] of [
  ["subprocess API", /\bsubprocess\b/u],
  ["shell execution", /\bos\.system\b|shell\s*=\s*True/u],
  ["Docker socket", /docker\.sock|npipe:\/\/\.\/pipe\/docker_engine/u],
  ["Podman socket", /podman\.sock/u],
  ["runtime socket path", /\/var\/run\//u],
]) {
  requireValue(!pattern.test(implementation), `Runtime foundation contains forbidden ${label}.`);
}

for (const path of [
  "docs/en/m2/README.md",
  "docs/en/m2/runtime-backend-adr.md",
  "docs/en/m2/broker-threat-model.md",
  "docs/ko/m2/README.md",
  "docs/ko/m2/runtime-backend-adr.md",
  "docs/ko/m2/broker-threat-model.md",
  "docs/CODEMAPS/README.md",
  "docs/CODEMAPS/backend.md",
]) {
  requireValue(await exists(path), `Missing M2 documentation: ${path}`);
}

if (errors.length > 0) {
  console.error("M2 runtime foundation check failed:");
  errors.forEach((error) => console.error(`- ${error}`));
  process.exitCode = 1;
} else {
  console.log(
    `M2 runtime foundation check passed (${expectedProtocolOperations.length} operations, ${expectedRequiredCapabilities.length} required capabilities, ${manifest.sourceFiles.length} frozen files).`,
  );
}
