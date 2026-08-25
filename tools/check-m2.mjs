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
  "bind_job",
  "list_managed",
];

const expectedJobProtocolOperations = [
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
  "runtime_fencing",
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
  "operation-fenced",
];

const expectedSourceFiles = [
  "backend/app/runtime/__init__.py",
  "backend/app/runtime/errors.py",
  "backend/app/runtime/models.py",
  "backend/app/runtime/policy.py",
  "backend/app/runtime/protocol.py",
  "backend/app/runtime/fencing.py",
  "backend/app/runtime/mock_backend.py",
  "backend/app/broker/__init__.py",
  "backend/app/broker/archive.py",
  "backend/app/broker/cancellation.py",
  "backend/app/broker/cancellation_arbitration.py",
  "backend/app/broker/cleanup.py",
  "backend/app/broker/diagnostics.py",
  "backend/app/broker/lifecycle.py",
  "backend/app/broker/lease.py",
  "backend/app/broker/live_state.py",
  "backend/app/broker/models.py",
  "backend/app/broker/orchestrator.py",
  "backend/app/broker/output_archive.py",
  "backend/app/broker/state.py",
  "backend/app/broker/sqlite_state.py",
  "backend/app/broker/state_mapping.py",
  "backend/app/broker/recovery.py",
  "backend/app/broker/state_composition.py",
  "backend/pyproject.toml",
  "backend/tests/runtime/support.py",
  "backend/tests/runtime/test_identity.py",
  "backend/tests/runtime/test_mock_backend.py",
  "backend/tests/runtime/test_name_collisions.py",
  "backend/tests/runtime/test_policy.py",
  "backend/tests/broker/test_archive.py",
  "backend/tests/broker/lease_support.py",
  "backend/tests/broker/test_cancellation_redaction.py",
  "backend/tests/broker/test_cleanup_concurrency.py",
  "backend/tests/broker/test_durable_cancellation.py",
  "backend/tests/broker/test_operation_ownership.py",
  "backend/tests/broker/test_owner_lease_runtime_fencing.py",
  "backend/tests/broker/test_lifecycle_control.py",
  "backend/tests/broker/test_orchestrator.py",
  "backend/tests/broker/test_output_archive.py",
  "backend/tests/broker/state_store_conformance.py",
  "backend/tests/broker/test_recovery.py",
  "backend/tests/broker/sqlite_recovery_child.py",
  "backend/tests/broker/test_sqlite_state_store.py",
  "backend/tests/broker/test_state_composition.py",
  "backend/tests/broker/test_state_mapping.py",
  "backend/tests/broker/test_state_store_conformance.py",
  "backend/tests/broker/test_state_store.py",
  "tools/check-m2.mjs",
  "tools/run-python-tests.mjs",
  "docs/en/m2/README.md",
  "docs/en/m2/runtime-backend-adr.md",
  "docs/en/m2/broker-threat-model.md",
  "docs/en/m2/broker-archive-foundation.md",
  "docs/en/m2/output-cancellation-redaction.md",
  "docs/en/m2/lifecycle-cleanup-state.md",
  "docs/en/m2/event-state-recovery.md",
  "docs/en/m2/sqlite-durable-state.md",
  "docs/en/m2/live-state-composition.md",
  "docs/en/m2/durable-cancellation-arbitration.md",
  "docs/en/m2/durable-operation-ownership.md",
  "docs/en/m2/owner-lease-runtime-fencing.md",
  "docs/ko/m2/README.md",
  "docs/ko/m2/runtime-backend-adr.md",
  "docs/ko/m2/broker-threat-model.md",
  "docs/ko/m2/broker-archive-foundation.md",
  "docs/ko/m2/output-cancellation-redaction.md",
  "docs/ko/m2/lifecycle-cleanup-state.md",
  "docs/ko/m2/event-state-recovery.md",
  "docs/ko/m2/sqlite-durable-state.md",
  "docs/ko/m2/live-state-composition.md",
  "docs/ko/m2/durable-cancellation-arbitration.md",
  "docs/ko/m2/durable-operation-ownership.md",
  "docs/ko/m2/owner-lease-runtime-fencing.md",
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
requireValue(manifest.securityBoundary.phaseCancellationInjectionImplemented === true, "Phase cancellation injection must be recorded.");
requireValue(manifest.securityBoundary.processLocalCleanupCoordinatorImplemented === true, "Process-local cleanup coordination must be recorded.");
requireValue(manifest.securityBoundary.durableStateInterfaceDefined === true, "Durable state interface must be recorded.");
requireValue(manifest.securityBoundary.brokerEventStateMappingDefined === true, "Broker event-state mapping must be recorded.");
requireValue(manifest.securityBoundary.durableAdapterConformanceSuiteImplemented === true, "Adapter conformance suite must be recorded.");
requireValue(manifest.securityBoundary.crashRestartRecoveryContractImplemented === true, "Crash/restart recovery must be recorded.");
requireValue(manifest.securityBoundary.candidateDurableStateStoreImplemented === true, "The SQLite candidate must be recorded.");
requireValue(manifest.securityBoundary.candidateDurableStateStoreProductEnabled === false, "The SQLite candidate must remain product-disabled.");
requireValue(manifest.securityBoundary.externalProcessRestartContractTested === true, "Separate-process restart evidence must be recorded.");
requireValue(manifest.securityBoundary.candidateLiveBrokerStateCompositionImplemented === true, "The inactive live-state composition must be recorded.");
requireValue(manifest.securityBoundary.candidateLiveBrokerStateCompositionProductEnabled === false, "The live-state composition must remain product-disabled.");
requireValue(manifest.securityBoundary.liveExecuteStateWiringTested === true, "Candidate execution state wiring must be tested.");
requireValue(manifest.securityBoundary.candidateDurableExternalCancellationImplemented === true, "Candidate durable external cancellation must be recorded.");
requireValue(manifest.securityBoundary.candidateDurableExternalCancellationProductEnabled === false, "Candidate durable cancellation must remain product-disabled.");
requireValue(manifest.securityBoundary.cancellationIntentBeforeRuntimeQuery === true, "Cancellation intent must precede runtime query.");
requireValue(manifest.securityBoundary.cancellationArbitrationCAS === true, "Cancellation arbitration must use CAS.");
requireValue(manifest.securityBoundary.restartSafeCancellationTested === true, "Restart-safe cancellation must be tested.");
requireValue(manifest.securityBoundary.candidateDurableOperationOwnershipImplemented === true, "Candidate durable ownership must be recorded.");
requireValue(manifest.securityBoundary.candidateDurableOperationOwnershipProductEnabled === false, "Candidate durable ownership must remain product-disabled.");
requireValue(manifest.securityBoundary.ownershipFencingStoreEnforced === true, "Store-enforced fencing must be recorded.");
requireValue(manifest.securityBoundary.staleOwnerRuntimeMutationGuarded === true, "Stale runtime mutation guards must be recorded.");
requireValue(manifest.securityBoundary.staleOwnerTerminalWriteRejected === true, "Stale terminal writes must be rejected.");
requireValue(manifest.securityBoundary.recoveryTakeoverFencingTested === true, "Recovery takeover fencing must be tested.");
requireValue(manifest.securityBoundary.schemaV1MigrationTested === true, "SQLite v1 migration must be tested.");
requireValue(manifest.securityBoundary.schemaV2MigrationTested === true, "SQLite v2 migration must be tested.");
requireValue(manifest.securityBoundary.ownershipFencingRuntimeEnforced === true, "Strict mock runtime fencing must be recorded.");
requireValue(manifest.securityBoundary.productRuntimeFencingEnforced === false, "Product runtime fencing must remain unclaimed.");
requireValue(manifest.securityBoundary.ownerLivenessImplemented === true, "Owner liveness must be recorded.");
requireValue(manifest.securityBoundary.leaseExpiryImplemented === true, "Lease expiry must be recorded.");
requireValue(manifest.securityBoundary.ownerHeartbeatImplemented === true, "Owner heartbeat must be recorded.");
requireValue(manifest.securityBoundary.productExternalCancellationWiring === false, "Product external cancellation wiring must remain absent.");
requireValue(manifest.securityBoundary.startupRecoveryAdmissionGateImplemented === true, "Startup recovery admission must be recorded.");
requireValue(manifest.securityBoundary.productRuntimeAcceptedByComposition === false, "The composition must reject product runtimes.");
requireValue(manifest.securityBoundary.durableStateStoreImplemented === false, "A product durable state store must not be claimed.");
requireValue(manifest.securityBoundary.productBrokerStateStoreWiringImplemented === false, "Product broker-to-store wiring must remain absent.");
requireValue(manifest.securityBoundary.distributedCleanupLeaseImplemented === false, "Distributed cleanup leasing must remain absent.");

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
  sameArray(manifest.contract.jobProtocolOperations, expectedJobProtocolOperations),
  "RuntimeJobBackend operation list drifted.",
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
  const declaration = operation === "bind_job" ? `def ${operation}(` : `async def ${operation}(`;
  requireValue(protocol.includes(declaration), `RuntimeBackend protocol is missing ${operation}.`);
}
requireValue(protocol.includes("class RuntimeJobBackend(Protocol)"), "RuntimeJobBackend protocol must be defined.");
for (const operation of expectedJobProtocolOperations) {
  requireValue(
    protocol.includes(`async def ${operation}(`),
    `RuntimeJobBackend protocol is missing ${operation}.`,
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
  ["RUN-007", "candidate-lease-runtime-fencing-tested"],
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
  ["BRK-006", "candidate-lease-aware-recovery-tested"],
  ["BRK-007", "candidate-lease-runtime-fenced-cancellation-tested"],
  ["BRK-008", "candidate-owner-lease-state-tested"],
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
requireValue(manifest.testContract.testCount === 113, "Runtime and broker test count must be 113.");
requireValue(manifest.testContract.archiveDefenseTests === 6, "Input archive defense test count must be 6.");
requireValue(manifest.testContract.outputArchiveDefenseTests === 3, "Output archive defense test count must be 3.");
requireValue(manifest.testContract.brokerOrchestrationTests === 8, "Broker orchestration test count must be 8.");
requireValue(manifest.testContract.brokerSecurityTests === 5, "Broker security test count must be 5.");
requireValue(manifest.testContract.identityPolicyTests === 2, "Identity policy test count must be 2.");
requireValue(manifest.testContract.lifecycleCancellationTests === 3, "Lifecycle cancellation test count must be 3.");
requireValue(manifest.testContract.lifecycleCancellationCheckpoints === 11, "Lifecycle cancellation checkpoint count must be 11.");
requireValue(manifest.testContract.cleanupConcurrencyTests === 3, "Cleanup concurrency test count must be 3.");
requireValue(manifest.testContract.durableStateTests === 7, "Durable state interface test count must be 7.");
requireValue(manifest.testContract.durableAdapterConformanceTests === 10, "Adapter conformance test count must be 10.");
requireValue(manifest.testContract.stateMappingTests === 5, "State mapping test count must be 5.");
requireValue(manifest.testContract.crashRecoveryTests === 4, "Crash recovery test count must be 4.");
requireValue(manifest.testContract.crashInjectionCheckpoints === 4, "Crash injection checkpoint count must be 4.");
requireValue(manifest.testContract.stateStoreUsesDatabase === true, "The candidate suite must use SQLite.");
requireValue(manifest.testContract.sqliteAdapterConformanceTests === 10, "SQLite conformance test count must be 10.");
requireValue(manifest.testContract.sqliteSpecificContractTests === 6, "SQLite-specific contract test count must be 6.");
requireValue(manifest.testContract.externalProcessHardExitTests === 1, "Hard-exit process test count must be 1.");
requireValue(manifest.testContract.stateCompositionTests === 9, "Live-state composition test count must be 9.");
requireValue(manifest.testContract.durableCancellationTests === 8, "Durable cancellation test count must be 8.");
requireValue(manifest.testContract.durableCancellationCrashCheckpoints === 5, "Durable cancellation checkpoint count must be 5.");
requireValue(manifest.testContract.operationOwnershipTests === 5, "Operation ownership test count must be 5.");
requireValue(manifest.testContract.operationOwnershipTestPath === "backend/tests/broker/test_operation_ownership.py", "Ownership test path drifted.");
requireValue(manifest.testContract.ownerLeaseRuntimeFencingTests === 4, "Owner lease/runtime fencing test count must be 4.");
requireValue(manifest.testContract.ownerLeaseRuntimeFencingTestPath === "backend/tests/broker/test_owner_lease_runtime_fencing.py", "Owner lease/runtime fencing test path drifted.");
requireValue(manifest.testContract.usesMockBackend === true, "Composition tests must use the mock backend.");
requireValue(manifest.testContract.usesProductRuntime === false, "Composition tests must not use a product runtime.");
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
const brokerCancellationArbitration = await readFile(join(root, "backend/app/broker/cancellation_arbitration.py"), "utf8");
const brokerCleanup = await readFile(join(root, "backend/app/broker/cleanup.py"), "utf8");
const brokerDiagnostics = await readFile(join(root, "backend/app/broker/diagnostics.py"), "utf8");
const brokerLifecycle = await readFile(join(root, "backend/app/broker/lifecycle.py"), "utf8");
const runtimeFencing = await readFile(join(root, "backend/app/runtime/fencing.py"), "utf8");
const runtimeMockBackend = await readFile(join(root, "backend/app/runtime/mock_backend.py"), "utf8");
const brokerLease = await readFile(join(root, "backend/app/broker/lease.py"), "utf8");
const brokerLiveState = await readFile(join(root, "backend/app/broker/live_state.py"), "utf8");
const brokerModels = await readFile(join(root, "backend/app/broker/models.py"), "utf8");
const brokerOrchestrator = await readFile(join(root, "backend/app/broker/orchestrator.py"), "utf8");
const brokerState = await readFile(join(root, "backend/app/broker/state.py"), "utf8");
const brokerSQLiteState = await readFile(join(root, "backend/app/broker/sqlite_state.py"), "utf8");
const brokerStateMapping = await readFile(join(root, "backend/app/broker/state_mapping.py"), "utf8");
const brokerRecovery = await readFile(join(root, "backend/app/broker/recovery.py"), "utf8");
const brokerStateComposition = await readFile(join(root, "backend/app/broker/state_composition.py"), "utf8");
const implementation = [
  protocol,
  models,
  policy,
  errorsSource,
  runtimeFencing,
  runtimeMockBackend,
  brokerArchive,
  brokerOutputArchive,
  brokerCancellation,
  brokerCancellationArbitration,
  brokerCleanup,
  brokerDiagnostics,
  brokerLifecycle,
  brokerLease,
  brokerLiveState,
  brokerModels,
  brokerOrchestrator,
  brokerState,
  brokerStateMapping,
  brokerRecovery,
  brokerStateComposition,
].join("\n");
for (const [label, pattern] of [
  ["subprocess API", /\bsubprocess\b/u],
  ["shell execution", /\bos\.system\b|shell\s*=\s*True/u],
  ["Docker socket", /docker\.sock|npipe:\/\/\.\/pipe\/docker_engine/u],
  ["Podman socket", /podman\.sock/u],
  ["runtime socket path", /\/var\/run\//u],
  ["filesystem tar extraction", /\.extract(?:all)?\(/u],
  ["temporary filesystem staging", /\btempfile\b|NamedTemporaryFile/u],
  ["database driver", /\bsqlite3\b|\bpsycopg\b|\basyncpg\b/u],
]) {
  requireValue(!pattern.test(implementation), `Runtime foundation contains forbidden ${label}.`);
}

requireValue(brokerSQLiteState.includes("import sqlite3"), "SQLite candidate must use the standard-library driver.");
for (const [label, pattern] of [
  ["product runtime socket", /docker\.sock|podman\.sock|\/var\/run\//u],
  ["external database driver", /\bpsycopg\b|\basyncpg\b/u],
  ["subprocess execution", /\bsubprocess\b|os\.system/u],
]) {
  requireValue(!pattern.test(brokerSQLiteState), "SQLite candidate contains forbidden " + label + ".");
}
requireValue(brokerSQLiteState.includes("PRAGMA journal_mode = WAL"), "SQLite candidate must enable WAL.");
requireValue(brokerSQLiteState.includes("PRAGMA synchronous = FULL"), "SQLite candidate must require FULL synchronization.");
requireValue(brokerSQLiteState.includes('connection.execute("BEGIN IMMEDIATE")'), "SQLite append must use BEGIN IMMEDIATE.");
requireValue(brokerSQLiteState.includes("PRAGMA user_version"), "SQLite candidate must version its schema.");
requireValue(brokerSQLiteState.includes("cls._validate_schema(connection)"), "Every SQLite connection must validate the exact schema.");
requireValue(brokerSQLiteState.includes("SQLITE_STATE_RETENTION_POLICY"), "SQLite retention policy must be explicit.");
requireValue(brokerSQLiteState.includes("SQLITE_STATE_SCHEMA_VERSION = 3"), "SQLite candidate must use schema v3.");
requireValue(brokerSQLiteState.includes("SQLITE_STATE_PREVIOUS_SCHEMA_VERSION = 2"), "SQLite candidate must recognize schema v2.");
requireValue(brokerSQLiteState.includes("SQLITE_STATE_LEGACY_SCHEMA_VERSION = 1"), "SQLite candidate must recognize legacy schema v1.");
requireValue(brokerSQLiteState.includes("def _migrate_v1_to_v2("), "SQLite candidate must define v1-to-v2 migration.");
requireValue(brokerSQLiteState.includes("def _migrate_v2_to_v3("), "SQLite candidate must define v2-to-v3 migration.");
requireValue(brokerSQLiteState.includes("DENSE_RANK() OVER"), "SQLite migration must derive owner generations deterministically.");
requireValue(brokerSQLiteState.includes("async def renew_ownership("), "SQLite candidate must renew ownership.");
requireValue(brokerSQLiteState.includes("async def verify_ownership("), "SQLite candidate must verify ownership.");
requireValue(brokerSQLiteState.includes("CREATE TABLE job_leases"), "SQLite candidate must persist current lease control.");
requireValue(brokerSQLiteState.includes("SQLITE_STATE_PRODUCT_ENABLED = False"), "SQLite candidate must remain inactive.");

requireValue(brokerArchive.includes('mode="r:"'), "Archive validator must reject compression.");
requireValue(brokerArchive.includes("compare_digest(canonical, payload)"), "Input archive validator must require canonical bytes.");
requireValue(brokerOutputArchive.includes('mode="r:"'), "Output archive validator must reject compression.");
requireValue(brokerOutputArchive.includes("compare_digest(canonical, payload)"), "Output archive validator must require canonical bytes.");
requireValue(brokerOutputArchive.includes("hash-mismatch"), "Output archive validator must reject byte substitution.");
requireValue(models.includes("class JobIdentity"), "Runtime model must define JobIdentity.");
requireValue(models.includes('return ("tcad.job_id", self.job_id)'), "JobIdentity label drifted.");
requireValue(protocol.includes("def bind_job(self, fence: RuntimeFencingContext)"), "Job lifecycle must require a runtime fencing context.");
requireValue(runtimeFencing.includes("class RuntimeFencingContext"), "Runtime fencing context must be defined.");
for (const label of ["tcad.job_id", "tcad.owner_id", "tcad.fencing_token"]) {
  requireValue(runtimeFencing.includes(label), `Runtime fencing context is missing label ${label}.`);
}
requireValue(runtimeMockBackend.includes("_runtime_fences"), "Strict mock runtime must retain the highest accepted fence.");
requireValue(runtimeMockBackend.includes("def bind_job("), "Strict mock runtime must expose job binding.");
requireValue(brokerOrchestrator.includes("TerminationReason.CANCELLATION"), "Broker cancellation reason drifted.");
requireValue(brokerOrchestrator.includes("handle.job_id != identity.job_id"), "Broker must reject cross-job cancellation handles.");
requireValue(brokerOrchestrator.includes("runtime.list_managed"), "Broker must verify zero managed objects through a bound runtime.");
requireValue(brokerOrchestrator.includes("self._backend.bind_job("), "Broker job lifecycle must bind a runtime fence.");
requireValue(brokerDiagnostics.includes("field(repr=False)"), "Internal diagnostics must hide raw fields from repr.");
requireValue(brokerDiagnostics.includes("_raw_detail"), "Internal diagnostics must retain raw detail.");
requireValue(!brokerModels.includes('"detail":'), "Public broker dictionaries must not expose raw detail.");
requireValue(manifest.lifecycleCancellationContract.checkpoints.length === 11, "Cancellation checkpoint manifest must contain 11 entries.");
for (const checkpoint of manifest.lifecycleCancellationContract.checkpoints) {
  requireValue(brokerLifecycle.includes(`= "${checkpoint}"`), `Lifecycle source is missing ${checkpoint}.`);
}
requireValue(brokerOrchestrator.includes("CancellationSignal | None"), "Broker execute must accept a typed cancellation signal.");
requireValue(brokerOrchestrator.includes("LifecycleCheckpoint.CLEANUP"), "Broker must retain the final cleanup cancellation fence.");
requireValue(brokerCleanup.includes("class JobCleanupCoordinator"), "Cleanup coordinator must be defined.");
requireValue(brokerCleanup.includes("async def lease"), "Cleanup coordinator must expose async job leases.");
requireValue(manifest.cleanupConcurrencyContract.alreadyAbsentIsSuccess === true, "Already-absent cleanup must be idempotent success.");
requireValue(manifest.cleanupConcurrencyContract.scope === "process-local", "Cleanup coordinator scope must remain process-local.");
requireValue(brokerState.includes("class DurableJobStateStore(Protocol)"), "Durable state protocol must be defined.");
for (const operation of manifest.durableStateContract.operations) {
  requireValue(brokerState.includes(`async def ${operation}(`), `Durable state protocol is missing ${operation}.`);
}
requireValue(brokerState.includes("expected_revision"), "State append must require an expected revision.");
for (const field of ["operation_sequence", "owner_id", "fencing_token", "lease_duration_ms", "retry", "backend", "classification"]) {
  requireValue(brokerState.includes(`    ${field}:`), `Durable event is missing ${field}.`);
}
requireValue(brokerState.includes("StateStoreErrorCode.REVISION_CONFLICT"), "State CAS conflict must be stable.");
requireValue(brokerState.includes("StateStoreErrorCode.OWNERSHIP_CONFLICT"), "Ownership conflict must be stable.");
requireValue(brokerState.includes("StateStoreErrorCode.LEASE_EXPIRED"), "Lease expiry must be stable.");
requireValue(brokerState.includes("StateStoreErrorCode.LEASE_ACTIVE"), "Live lease refusal must be stable.");
requireValue(brokerState.includes("class DurableOperationOwnership"), "Durable ownership model must be defined.");
requireValue(brokerState.includes("class DurableOperationGuard"), "Durable ownership guard must be defined.");
requireValue(brokerState.includes("async def renew_ownership("), "Durable state protocol must renew ownership.");
requireValue(brokerState.includes("async def verify_ownership("), "Durable state protocol must verify ownership.");
requireValue(brokerState.includes("async def run_with_lease_heartbeat("), "Durable ownership guard must heartbeat guarded awaits.");
requireValue(brokerLease.includes("class OwnerLeasePolicy"), "Bounded owner lease policy must be defined.");
requireValue(brokerState.includes("def validate_operation_ownership("), "Shared ownership transition validation must be defined.");
requireValue(brokerState.includes("previous.fencing_token + 1"), "Takeover must increment the fencing token exactly once.");
requireValue(!brokerState.includes("raw_detail"), "Durable event source must not expose raw detail.");
requireValue(brokerState.includes("_operation_slots"), "State adapter must reject operation-slot reuse.");
requireValue(brokerStateMapping.includes("class BrokerStateMapper"), "Broker state mapper must be defined.");
requireValue(brokerStateMapping.includes("uuid5("), "Mapped event IDs must be deterministic UUID v5 values.");
requireValue(brokerStateMapping.includes("class StateEventRecorder"), "State batch recorder must be defined.");
requireValue(brokerLiveState.includes("class LiveStateSession"), "Live state session must be defined.");
requireValue(brokerLiveState.includes("uuid5("), "Live state IDs must use deterministic UUID v5 values.");
requireValue(brokerLiveState.includes("await self._store.append("), "Live state writes must await the durable store.");
requireValue(brokerLiveState.includes("await self._store.renew_ownership("), "Live state must renew exact ownership.");
requireValue(brokerLiveState.includes("if self._failed:"), "A failed live-state session must stop later writes.");
requireValue(brokerStateComposition.includes("BROKER_STATE_COMPOSITION_PRODUCT_ENABLED = False"), "Live-state composition must remain inactive.");
requireValue(brokerStateComposition.includes("broker.runtime_kind is not RuntimeKind.MOCK"), "Live-state composition must reject product runtimes.");
requireValue(brokerStateComposition.includes("class DurableBrokerComposition"), "Durable broker composition must be defined.");
requireValue(brokerStateComposition.includes("remaining = await self._store.scan_recoverable(limit=1)"), "Startup must perform a final recovery scan.");
requireValue(brokerStateComposition.indexOf("current = await self._store.load(identity)") < brokerStateComposition.indexOf("session = LiveStateSession("), "Admission must load existing state before opening a live session.");
requireValue(brokerStateComposition.includes("str(uuid4())"), "Every composition admission must create a fresh owner attempt.");
requireValue(brokerStateComposition.includes("current.ownership.fencing_token + 1"), "Cancellation takeover must increment the fencing token.");
requireValue(brokerOrchestrator.indexOf("BrokerState.VALIDATING") < brokerOrchestrator.indexOf("probe = await self._run_owned("), "Validating state must precede the runtime probe.");
requireValue(brokerOrchestrator.includes("await self._event("), "Broker phase events must be awaited.");
requireValue(brokerRecovery.includes("class CrashRecoveryCoordinator"), "Crash recovery coordinator must be defined.");
requireValue(brokerRecovery.includes("owner_id = str(uuid4())"), "Every recovery claim must create a fresh owner attempt.");
requireValue(brokerRecovery.includes("class DurableOperationGuard") || brokerRecovery.includes("DurableOperationGuard("), "Recovery must use a durable ownership guard.");
requireValue(brokerRecovery.includes("RecoveryStatus.OWNERSHIP_CONFLICT"), "Recovery must report ownership conflicts.");
requireValue(brokerRecovery.includes("RecoveryStatus.OWNER_ACTIVE"), "Recovery must refuse takeover of a live owner.");
for (const checkpoint of manifest.crashRestartRecoveryContract.checkpoints) {
  requireValue(brokerRecovery.includes(`= "${checkpoint}"`), `Recovery source is missing ${checkpoint}.`);
}
requireValue(manifest.eventStateMappingContract.candidateExecuteWiringImplemented === true, "Candidate execution wiring must be recorded.");
requireValue(manifest.eventStateMappingContract.candidateExternalCancellationWiringImplemented === true, "Candidate external cancellation mapping must be recorded.");
requireValue(manifest.eventStateMappingContract.cancellationIntentClassificationPreserved === true, "Cancellation classification must survive cleanup mapping.");
requireValue(manifest.eventStateMappingContract.productLiveBrokerWiringImplemented === false, "Product live broker wiring must remain absent.");
requireValue(manifest.adapterConformanceContract.inMemoryBackingDurable === false, "Memory conformance backing must not be durable.");
requireValue(manifest.durableStateContract.candidateDurableAdapterImplemented === true, "SQLite durable adapter candidate must be recorded.");
requireValue(manifest.durableStateContract.durableAdapterImplemented === false, "Product durable adapter must remain disabled.");
requireValue(manifest.durableStateContract.candidateExecuteWiringImplemented === true, "Candidate durable execution wiring must be recorded.");
requireValue(manifest.durableStateContract.productBrokerWiringImplemented === false, "Product durable broker wiring must remain absent.");
requireValue(manifest.adapterConformanceContract.sqliteCandidateTested === true, "SQLite must run the common conformance suite.");
requireValue(sameArray(manifest.adapterConformanceContract.cases, [
  "protocol-empty-state",
  "reopen-visibility",
  "idempotent-replay",
  "event-and-operation-conflicts",
  "concurrent-cas",
  "owner-takeover-stale-token-after-reopen",
  "live-lease-renewal-revision-neutral-after-reopen",
  "expired-owner-rejected",
  "recovery-waits-cancellation-preempts-expired-recovery-takes-over",
  "bounded-recovery-pagination",
]), "Adapter conformance case list drifted.");
requireValue(manifest.adapterConformanceContract.productAdapterTested === false, "No product state adapter may be claimed.");
requireValue(manifest.crashRestartRecoveryContract.externalProcessRestartTested === true, "Separate-process durability must be tested.");
requireValue(manifest.crashRestartRecoveryContract.processHardExitTested === true, "Hard-exit durability must be tested.");
requireValue(manifest.crashRestartRecoveryContract.hardExitCheckpoint === "after-claim", "Hard-exit checkpoint drifted.");
requireValue(manifest.crashRestartRecoveryContract.durableDatabaseTested === true, "SQLite commit durability must be tested.");
requireValue(manifest.crashRestartRecoveryContract.powerLossTested === false, "Power-loss durability must remain unclaimed.");
requireValue(manifest.crashRestartRecoveryContract.recoversAsSucceeded === false, "Recovery must never synthesize success.");
requireValue(manifest.crashRestartRecoveryContract.startupAdmissionTested === true, "Startup recovery admission must be tested.");
requireValue(manifest.crashRestartRecoveryContract.finalRecoverableRescanTested === true, "Startup must verify an empty recovery tail.");
requireValue(manifest.sqliteDurableStateContract.adapter === "python-stdlib-sqlite3", "SQLite adapter identity drifted.");
requireValue(manifest.sqliteDurableStateContract.schemaVersion === 3, "SQLite schema version drifted.");
requireValue(manifest.sqliteDurableStateContract.previousSchemaVersion === 2, "SQLite previous schema version drifted.");
requireValue(manifest.sqliteDurableStateContract.legacySchemaVersion === 1, "SQLite legacy schema version drifted.");
requireValue(manifest.sqliteDurableStateContract.v1MigrationTested === true, "SQLite v1 migration must be tested.");
requireValue(manifest.sqliteDurableStateContract.v2MigrationTested === true, "SQLite v2 migration must be tested.");
requireValue(manifest.sqliteDurableStateContract.migrationPreservesRows === true, "SQLite migration must preserve rows.");
requireValue(manifest.sqliteDurableStateContract.localFileOnly === true, "SQLite candidate must remain local-file-only.");
requireValue(manifest.sqliteDurableStateContract.memoryDatabaseAccepted === false, "SQLite memory databases must remain forbidden.");
requireValue(manifest.sqliteDurableStateContract.uriDatabaseAccepted === false, "SQLite URI databases must remain forbidden.");
requireValue(manifest.sqliteDurableStateContract.journalMode === "wal", "SQLite WAL contract drifted.");
requireValue(manifest.sqliteDurableStateContract.synchronous === "full", "SQLite synchronization contract drifted.");
requireValue(manifest.sqliteDurableStateContract.appendTransaction === "begin-immediate", "SQLite append transaction drifted.");
requireValue(manifest.sqliteDurableStateContract.eventLogAppendOnly === true, "SQLite event log must remain append-only.");
requireValue(manifest.sqliteDurableStateContract.leaseControlRowMutable === true, "SQLite current lease control must be mutable.");
requireValue(manifest.sqliteDurableStateContract.automaticRetention === false, "Automatic state retention must remain disabled.");
requireValue(manifest.sqliteDurableStateContract.retentionPolicy === "append-only-events-explicit-lease-renewal", "SQLite retention policy drifted.");
requireValue(manifest.sqliteDurableStateContract.renewalAdvancesJobRevision === false, "SQLite renewal must not advance job revision.");
requireValue(manifest.sqliteDurableStateContract.forwardOnlyMigration === true, "SQLite migration must remain forward-only.");
requireValue(manifest.sqliteDurableStateContract.unknownForwardVersionAccepted === false, "Unknown SQLite versions must fail closed.");
requireValue(manifest.sqliteDurableStateContract.exactSchemaRequired === true, "SQLite schema mismatches must fail closed.");
requireValue(manifest.sqliteDurableStateContract.productEnabled === false, "SQLite candidate must remain product-disabled.");
requireValue(manifest.sqliteDurableStateContract.candidateMockExecutionWiring === true, "SQLite candidate mock execution wiring must be recorded.");
requireValue(manifest.sqliteDurableStateContract.productLiveBrokerWiring === false, "Product SQLite wiring must remain absent.");
requireValue(manifest.sqliteDurableStateContract.powerLossTested === false, "SQLite power-loss proof must remain unclaimed.");
requireValue(manifest.sqliteDurableStateContract.backupRestoreTested === false, "SQLite backup and restore must remain unclaimed.");
requireValue(manifest.sqliteDurableStateContract.multiHostTested === false, "SQLite multi-host support must remain unclaimed.");

requireValue(manifest.liveStateCompositionContract.productEnabled === false, "Live-state composition must remain product-disabled.");
requireValue(manifest.liveStateCompositionContract.acceptedRuntime === "mock", "Live-state composition must remain mock-only.");
requireValue(manifest.liveStateCompositionContract.productRuntimeAccepted === false, "Product runtime kinds must remain rejected.");
requireValue(manifest.liveStateCompositionContract.directBrokerExecutionPersisted === false, "Direct broker execution must remain non-persisted.");
requireValue(manifest.liveStateCompositionContract.executeWiring === true, "Candidate execute wiring must be implemented.");
requireValue(manifest.liveStateCompositionContract.candidateExternalCancelWiring === true, "Candidate external cancellation wiring must be implemented.");
requireValue(manifest.liveStateCompositionContract.productExternalCancelWiring === false, "Product external cancellation wiring must remain absent.");
requireValue(manifest.liveStateCompositionContract.directBrokerCancellationPersisted === false, "Direct broker cancellation must remain non-persisted.");
for (const key of [
  "firstDurableStateBeforeRuntimeProbe",
  "startupRecoveryBeforeAdmission",
  "startupPagesBounded",
  "finalRecoverableRescan",
  "phaseWritesAwaited",
  "firstWriteFailureStopsProgress",
  "cleanupRunsAfterWriteFailure",
  "terminalWriteFailureLeavesRecoverablePrefix",
  "deterministicUuidV5",
]) {
  requireValue(manifest.liveStateCompositionContract[key] === true, `${key} must remain true.`);
}
for (const key of [
  "existingJobReadmissionAccepted",
  "terminalWriteFailureCanReportSuccess",
  "rawStoreDetailPublic",
  "serviceTransport",
  "runtimeSocket",
]) {
  requireValue(manifest.liveStateCompositionContract[key] === false, `${key} must remain false.`);
}

requireValue(manifest.durableCancellationContract.productEnabled === false, "Durable cancellation must remain product-disabled.");
requireValue(manifest.durableCancellationContract.acceptedRuntime === "mock", "Durable cancellation must remain mock-only.");
requireValue(manifest.durableCancellationContract.checkpoints.length === 5, "Durable cancellation must define five checkpoints.");
for (const checkpoint of manifest.durableCancellationContract.checkpoints) {
  requireValue(brokerCancellationArbitration.includes(`= "${checkpoint}"`), `Durable cancellation source is missing ${checkpoint}.`);
}
for (const key of [
  "candidateCompositionWiring",
  "intentWriteBeforeRuntimeQuery",
  "compareAndSwapArbitration",
  "processLocalLease",
  "firstWriteFailureStopsRuntimeContact",
  "laterWriteFailureStopsCancellationProgress",
  "cleanupRunsAfterWriteFailure",
  "cleanupIntentClassificationPreserved",
  "alreadyAbsentConverges",
  "volumeOnlyConverges",
  "restartNeverSynthesizesSuccess",
]) {
  requireValue(manifest.durableCancellationContract[key] === true, `${key} must remain true.`);
}
for (const key of [
  "directBrokerCancelPersisted",
  "missingStateAccepted",
  "terminalStateAccepted",
  "cancellingOrCleaningReadmissionAccepted",
  "terminalWriteFailureCanReportCancelled",
  "distributedLease",
  "serviceTransport",
  "runtimeSocket",
  "externalProcessHardExitTested",
  "powerLossTested",
]) {
  requireValue(manifest.durableCancellationContract[key] === false, `${key} must remain false.`);
}
requireValue(brokerCancellation.includes("intent_persisted: bool = False"), "Cancellation outcome must expose persisted intent.");
requireValue(brokerStateMapping.includes("isinstance(outcome, CancellationOutcome)"), "Cancellation outcomes must preserve cancellation intent in mapping.");
requireValue(brokerStateComposition.includes("expected_revision=current.revision"), "Cancellation intent CAS must start from the loaded revision.");
const cancellationIntentAppend = brokerStateComposition.indexOf("await session.record(");
const cancellationRuntimeEntry = brokerStateComposition.indexOf("return await self._broker._cancel_with_state_session_locked(");
requireValue(cancellationIntentAppend >= 0 && cancellationIntentAppend < cancellationRuntimeEntry, "Cancellation intent append must precede runtime entry.");
requireValue(brokerOrchestrator.includes("intent_persisted=state_session is not None"), "Durable cancellation outcome must retain intent admission.");
requireValue(brokerOrchestrator.includes("ErrorCode.OPERATION_FENCED"), "Broker must normalize stale ownership.");
requireValue(brokerOrchestrator.includes("await self._run_owned("), "Broker runtime boundaries must run with lease heartbeat.");

const ownershipContract = manifest.operationOwnershipContract;
requireValue(ownershipContract.productEnabled === false, "Operation ownership must remain product-disabled.");
requireValue(ownershipContract.acceptedRuntime === "mock", "Operation ownership must remain mock-only.");
requireValue(ownershipContract.ownerIdType === "uuid", "Owner attempts must use UUIDs.");
requireValue(ownershipContract.initialExecutionToken === 1, "Execution fencing must start at token 1.");
requireValue(ownershipContract.takeoverTokenIncrement === 1, "Takeover fencing must increment by 1.");
requireValue(sameArray(ownershipContract.takeoverStates, ["cancelling", "cleaning"]), "Ownership takeover states drifted.");
requireValue(ownershipContract.stablePublicCode === "operation-fenced", "Ownership public error drifted.");
requireValue(sameArray(ownershipContract.runtimeFenceLabels, ["tcad.job_id", "tcad.owner_id", "tcad.fencing_token"]), "Runtime fence labels drifted.");
for (const key of [
  "eventsPersistOwnerAndToken",
  "appendEnforcesOwnership",
  "verifyOwnershipImplemented",
  "verifyOwnershipExpectedRevision",
  "executionCancellationRecoveryCompetitionTested",
  "cooperativeApplicationFence",
  "runtimeEnforced",
  "ownerLiveness",
  "leaseExpiry",
  "ownerHeartbeat",
  "recoveryRequiresExpiredLease",
  "cancellationPreemptsLiveLease",
  "heartbeatCancelsPythonAwaitable",
  "runtimeRejectsLowerToken",
  "runtimeRejectsSameTokenDifferentOwner",
  "runtimeRejectsCrossJobContext",
]) {
  requireValue(ownershipContract[key] === true, `${key} must remain true.`);
}
for (const key of [
  "staleOwnerAppendAccepted",
  "staleOwnerRuntimeMutationAccepted",
  "staleOwnerCleanupAccepted",
  "staleOwnerTerminalAppendAccepted",
  "productNativeRuntimeEnforced",
  "verificationAndRuntimeCallAtomic",
  "inFlightCallRevocation",
  "multiHost",
  "clockSkewBounded",
]) {
  requireValue(ownershipContract[key] === false, `${key} must remain false.`);
}

const leaseContract = manifest.ownerLeaseRuntimeFencingContract;
requireValue(leaseContract.productEnabled === false, "Owner lease/runtime fencing must remain product-disabled.");
requireValue(leaseContract.acceptedRuntime === "mock", "Owner lease/runtime fencing must remain strict-mock-only.");
requireValue(leaseContract.clock === "utc-epoch-milliseconds", "Owner lease clock contract drifted.");
requireValue(leaseContract.defaultDurationMs === 30000, "Default owner lease duration drifted.");
requireValue(leaseContract.defaultHeartbeatIntervalMs === 10000, "Default owner heartbeat interval drifted.");
requireValue(leaseContract.maxDurationMs === 300000, "Maximum owner lease duration drifted.");
requireValue(sameArray(leaseContract.runtimeFenceLabels, ["tcad.job_id", "tcad.owner_id", "tcad.fencing_token"]), "Owner lease runtime labels drifted.");
for (const key of [
  "currentExpiryPersisted",
  "renewalRevisionNeutral",
  "expiredOwnerRejected",
  "recoveryRequiresExpiredLease",
  "cancellationPreemptsLiveLease",
  "heartbeatBeforeDuringAfterAwait",
  "heartbeatLossCancelsPythonAwaitable",
  "jobLifecycleRequiresRuntimeBinding",
  "strictMockRejectsLowerToken",
  "strictMockRejectsSameTokenDifferentOwner",
  "strictMockRejectsCrossJobContext",
]) {
  requireValue(leaseContract[key] === true, "Lease contract true field drifted: " + key + ".");
}
for (const key of [
  "sameOwnerCanRenewAfterExpiry",
  "productNativeRuntimeEnforced",
  "storeCommitAndRuntimeActivationAtomic",
  "nativeInFlightRevocationProven",
  "clockSkewBounded",
  "multiHost",
]) {
  requireValue(leaseContract[key] === false, "Lease contract false field drifted: " + key + ".");
}

for (const code of manifest.liveStateCompositionContract.compositionErrorCodes) {
  requireValue(brokerStateComposition.includes(`= "${code}"`), `Composition source is missing ${code}.`);
}

for (const path of [
  "docs/en/m2/README.md",
  "docs/en/m2/runtime-backend-adr.md",
  "docs/en/m2/broker-threat-model.md",
  "docs/en/m2/broker-archive-foundation.md",
  "docs/en/m2/output-cancellation-redaction.md",
  "docs/en/m2/lifecycle-cleanup-state.md",
  "docs/en/m2/event-state-recovery.md",
  "docs/en/m2/sqlite-durable-state.md",
  "docs/en/m2/live-state-composition.md",
  "docs/en/m2/durable-cancellation-arbitration.md",
  "docs/en/m2/durable-operation-ownership.md",
  "docs/en/m2/owner-lease-runtime-fencing.md",
  "docs/ko/m2/README.md",
  "docs/ko/m2/runtime-backend-adr.md",
  "docs/ko/m2/broker-threat-model.md",
  "docs/ko/m2/broker-archive-foundation.md",
  "docs/ko/m2/output-cancellation-redaction.md",
  "docs/ko/m2/lifecycle-cleanup-state.md",
  "docs/ko/m2/event-state-recovery.md",
  "docs/ko/m2/sqlite-durable-state.md",
  "docs/ko/m2/live-state-composition.md",
  "docs/ko/m2/durable-cancellation-arbitration.md",
  "docs/ko/m2/durable-operation-ownership.md",
  "docs/ko/m2/owner-lease-runtime-fencing.md",
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
    `M2 runtime foundation check passed (${expectedProtocolOperations.length} global + ${expectedJobProtocolOperations.length} job operations, ${expectedRequiredCapabilities.length} required capabilities, ${manifest.sourceFiles.length} frozen files).`,
  );
}
