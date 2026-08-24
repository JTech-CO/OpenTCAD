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
  "identity-mismatch",
  "volume-not-found",
  "container-not-found",
  "invalid-state",
  "stale-state",
  "start-failed",
  "wait-failed",
  "kill-failed",
  "cancellation-rejected",
  "cleanup-failed",
  "input-archive-rejected",
  "output-archive-rejected",
  "artifact-rejected",
];

const expectedSourceFiles = [
  "backend/app/runtime/__init__.py",
  "backend/app/runtime/errors.py",
  "backend/app/runtime/models.py",
  "backend/app/runtime/policy.py",
  "backend/app/runtime/protocol.py",
  "backend/app/runtime/mock_backend.py",
  "backend/app/broker/__init__.py",
  "backend/app/broker/archive.py",
  "backend/app/broker/cancellation.py",
  "backend/app/broker/diagnostics.py",
  "backend/app/broker/models.py",
  "backend/app/broker/orchestrator.py",
  "backend/app/broker/output_archive.py",
  "backend/pyproject.toml",
  "backend/tests/runtime/support.py",
  "backend/tests/runtime/test_identity.py",
  "backend/tests/runtime/test_mock_backend.py",
  "backend/tests/runtime/test_name_collisions.py",
  "backend/tests/runtime/test_policy.py",
  "backend/tests/broker/test_archive.py",
  "backend/tests/broker/test_cancellation_redaction.py",
  "backend/tests/broker/test_orchestrator.py",
  "backend/tests/broker/test_output_archive.py",
  "tools/check-m2.mjs",
  "tools/run-python-tests.mjs",
  "docs/en/m2/README.md",
  "docs/en/m2/runtime-backend-adr.md",
  "docs/en/m2/broker-threat-model.md",
  "docs/en/m2/broker-archive-foundation.md",
  "docs/en/m2/output-cancellation-redaction.md",
  "docs/ko/m2/README.md",
  "docs/ko/m2/runtime-backend-adr.md",
  "docs/ko/m2/broker-threat-model.md",
  "docs/ko/m2/broker-archive-foundation.md",
  "docs/ko/m2/output-cancellation-redaction.md",
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
  manifest.scope === "engine-independent-broker-foundation-only",
  "M2 scope must remain engine-independent-broker-foundation-only.",
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

requireValue(manifest.securityBoundary.brokerLibraryImplemented === true, "Mock broker library must be recorded.");
requireValue(manifest.securityBoundary.canonicalInputArchiveImplemented === true, "Canonical input archive must be recorded.");
requireValue(manifest.securityBoundary.filesystemExtractionPerformed === false, "Archive validation must remain in memory.");
requireValue(manifest.securityBoundary.compressedArchiveAccepted === false, "Compressed archives must remain forbidden.");
requireValue(manifest.securityBoundary.canonicalOutputArchiveImplemented === true, "Canonical output archive must be recorded.");
requireValue(manifest.securityBoundary.cancellationIdentityImplemented === true, "Cancellation identity must be recorded.");
requireValue(manifest.securityBoundary.structuredPublicEventsImplemented === true, "Structured public events must be recorded.");
requireValue(manifest.securityBoundary.internalRawDiagnosticSeparated === true, "Internal diagnostic separation must be recorded.");
requireValue(manifest.securityBoundary.rawDiagnosticExposedPublicly === false, "Raw diagnostics must remain private.");

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
  ["RUN-007", "mock-broker-security-tested"],
]);
requireValue(workItems.size === expectedWorkItems.size, "M2 work item set drifted.");
for (const [id, status] of expectedWorkItems) {
  requireValue(workItems.get(id) === status, `${id} must remain ${status}.`);
}

const brokerWorkItems = new Map(manifest.brokerWorkItems.map((item) => [item.id, item.status]));
const expectedBrokerWorkItems = [
  ["BRK-001", "foundation-tested"],
  ["BRK-003", "mock-lifecycle-tested"],
  ["BRK-004", "canonical-input-output-archive-tested"],
  ["BRK-006", "mock-reconciliation-tested"],
  ["BRK-007", "mock-cancellation-identity-tested"],
  ["BRK-008", "structured-redaction-tested"],
];
requireValue(brokerWorkItems.size === expectedBrokerWorkItems.length, "M2 broker work item set drifted.");
for (const [id, status] of expectedBrokerWorkItems) {
  requireValue(brokerWorkItems.get(id) === status, `${id} must remain ${status}.`);
}

requireValue(manifest.archiveContract.format === "ustar-uncompressed", "Archive format drifted.");
requireValue(manifest.archiveContract.filesystemExtraction === false, "Archive extraction must remain memory-only.");
requireValue(manifest.archiveContract.compressionAccepted === false, "Archive compression must remain forbidden.");
requireValue(manifest.archiveContract.specialFilesAccepted === false, "Archive special files must remain forbidden.");
requireValue(sameArray(manifest.archiveContract.directions, ["input", "output"]), "Archive directions drifted.");
requireValue(manifest.archiveContract.canonicalByteRebuildRequired === true, "Canonical rebuild must remain required.");
requireValue(manifest.archiveContract.caseFoldCollisionsAccepted === false, "Case-fold collisions must remain forbidden.");
requireValue(manifest.archiveContract.outputEmptyRegularFilesAccepted === true, "Empty regular output files must remain supported.");

requireValue(manifest.identityContract.labelKey === "tcad.job_id", "Cancellation label key drifted.");
requireValue(manifest.identityContract.kindIndependent === true, "Job identity must remain kind-independent.");
requireValue(manifest.identityContract.crossJobHandlesAccepted === false, "Cross-job cancellation handles must remain forbidden.");
requireValue(manifest.identityContract.zeroObjectRecheck === true, "Cancellation must retain zero-object recheck.");

requireValue(manifest.redactionContract.publicRawDetail === false, "Public raw detail must remain forbidden.");
requireValue(manifest.redactionContract.publicUnknownBackend === false, "Unknown public backend values must remain forbidden.");
requireValue(manifest.redactionContract.internalRawFieldsReprVisible === false, "Internal raw fields must remain repr-hidden.");

requireValue(manifest.testContract.command === "npm run test:runtime", "Runtime test command drifted.");
requireValue(manifest.testContract.testCount === 39, "Runtime and broker test count must be 39.");
requireValue(manifest.testContract.archiveDefenseTests === 6, "Input archive defense test count must be 6.");
requireValue(manifest.testContract.outputArchiveDefenseTests === 3, "Output archive defense test count must be 3.");
requireValue(manifest.testContract.brokerOrchestrationTests === 8, "Broker orchestration test count must be 8.");
requireValue(manifest.testContract.brokerSecurityTests === 5, "Broker security test count must be 5.");
requireValue(manifest.testContract.identityPolicyTests === 2, "Identity policy test count must be 2.");
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
  "backend/app/broker/service.py",
  "backend/app/broker/transport.py",
  "backend/app/worker",
]) {
  requireValue(!(await exists(path)), `Blocked product implementation exists: ${path}`);
}

const brokerArchive = await readFile(join(root, "backend/app/broker/archive.py"), "utf8");
const brokerOutputArchive = await readFile(join(root, "backend/app/broker/output_archive.py"), "utf8");
const brokerCancellation = await readFile(join(root, "backend/app/broker/cancellation.py"), "utf8");
const brokerDiagnostics = await readFile(join(root, "backend/app/broker/diagnostics.py"), "utf8");
const brokerModels = await readFile(join(root, "backend/app/broker/models.py"), "utf8");
const brokerOrchestrator = await readFile(join(root, "backend/app/broker/orchestrator.py"), "utf8");
const implementation = [
  protocol,
  models,
  policy,
  errorsSource,
  await readFile(join(root, "backend/app/runtime/mock_backend.py"), "utf8"),
  brokerArchive,
  brokerOutputArchive,
  brokerCancellation,
  brokerDiagnostics,
  brokerModels,
  brokerOrchestrator,
].join("\n");
for (const [label, pattern] of [
  ["subprocess API", /\bsubprocess\b/u],
  ["shell execution", /\bos\.system\b|shell\s*=\s*True/u],
  ["Docker socket", /docker\.sock|npipe:\/\/\.\/pipe\/docker_engine/u],
  ["Podman socket", /podman\.sock/u],
  ["runtime socket path", /\/var\/run\//u],
  ["filesystem tar extraction", /\.extract(?:all)?\(/u],
  ["temporary filesystem staging", /\btempfile\b|NamedTemporaryFile/u],
]) {
  requireValue(!pattern.test(implementation), `Runtime foundation contains forbidden ${label}.`);
}

requireValue(brokerArchive.includes('mode="r:"'), "Archive validator must reject compression.");
requireValue(brokerArchive.includes("compare_digest(canonical, payload)"), "Input archive validator must require canonical bytes.");
requireValue(brokerOutputArchive.includes('mode="r:"'), "Output archive validator must reject compression.");
requireValue(brokerOutputArchive.includes("compare_digest(canonical, payload)"), "Output archive validator must require canonical bytes.");
requireValue(brokerOutputArchive.includes("hash-mismatch"), "Output archive validator must reject byte substitution.");
requireValue(models.includes("class JobIdentity"), "Runtime model must define JobIdentity.");
requireValue(models.includes('return ("tcad.job_id", self.job_id)'), "JobIdentity label drifted.");
requireValue(protocol.includes("create_volume(self, identity: JobIdentity)"), "Volume creation must require JobIdentity.");
requireValue(brokerOrchestrator.includes("TerminationReason.CANCELLATION"), "Broker cancellation reason drifted.");
requireValue(brokerOrchestrator.includes("handle.job_id != identity.job_id"), "Broker must reject cross-job cancellation handles.");
requireValue(brokerOrchestrator.includes("list_managed(identity.job_id)"), "Broker must verify zero managed objects.");
requireValue(brokerDiagnostics.includes("field(repr=False)"), "Internal diagnostics must hide raw fields from repr.");
requireValue(brokerDiagnostics.includes("_raw_detail"), "Internal diagnostics must retain raw detail.");
requireValue(!brokerModels.includes('"detail":'), "Public broker dictionaries must not expose raw detail.");

for (const path of [
  "docs/en/m2/README.md",
  "docs/en/m2/runtime-backend-adr.md",
  "docs/en/m2/broker-threat-model.md",
  "docs/en/m2/broker-archive-foundation.md",
  "docs/en/m2/output-cancellation-redaction.md",
  "docs/ko/m2/README.md",
  "docs/ko/m2/runtime-backend-adr.md",
  "docs/ko/m2/broker-threat-model.md",
  "docs/ko/m2/broker-archive-foundation.md",
  "docs/ko/m2/output-cancellation-redaction.md",
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
