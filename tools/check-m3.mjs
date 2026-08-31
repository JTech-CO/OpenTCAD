import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const read = (path) => readFileSync(resolve(root, path));
const json = (path) => JSON.parse(read(path).toString("utf8"));
const requireValue = (condition, message) => {
  if (!condition) {
    throw new Error(message);
  }
};
const exactKeys = (value, keys, label) => {
  requireValue(value && typeof value === "object" && !Array.isArray(value), label + " must be an object.");
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  requireValue(JSON.stringify(actual) === JSON.stringify(expected), label + " shape drifted.");
};
const digest = (path) => createHash("sha256").update(read(path)).digest("hex");

const gateIds = [
  "runtime-adapters",
  "native-fencing",
  "local-transport",
  "lifecycle-integration",
  "credentials-and-scheduler",
  "power-loss",
  "platform-qualification",
  "solver-release",
];
const manifest = json("validation/manifests/m3-entry-gates.json");
exactKeys(
  manifest,
  ["schemaVersion", "productEnabled", "approvalId", "approvedBy", "approvedAt", "gates", "runtime"],
  "M3 manifest",
);
requireValue(manifest.schemaVersion === 1, "M3 schema version drifted.");
requireValue(manifest.productEnabled === false, "M3 must remain disabled without all external evidence.");
requireValue(manifest.approvalId === null && manifest.approvedBy === null && manifest.approvedAt === null, "Disabled M3 cannot carry global approval.");
requireValue(Array.isArray(manifest.gates) && manifest.gates.length === gateIds.length, "M3 must contain exactly eight gates.");
requireValue(
  JSON.stringify(manifest.gates.map((gate) => gate.id)) === JSON.stringify(gateIds),
  "M3 gate order or identity drifted.",
);
for (const gate of manifest.gates) {
  exactKeys(gate, ["id", "approved", "approvedBy", "approvedAt", "evidence"], "M3 gate " + gate.id);
  requireValue(gate.approved === false, gate.id + " cannot be approved by contract evidence alone.");
  requireValue(gate.approvedBy === null && gate.approvedAt === null, gate.id + " has unreviewed approval metadata.");
  requireValue(Array.isArray(gate.evidence) && gate.evidence.length > 0, gate.id + " must explain its blocked state with evidence.");
  for (const evidence of gate.evidence) {
    exactKeys(evidence, ["path", "sha256"], gate.id + " evidence");
    requireValue(digest(evidence.path) === evidence.sha256, gate.id + " evidence drifted: " + evidence.path);
  }
}
exactKeys(manifest.runtime, ["grants"], "M3 runtime authority");
requireValue(
  manifest.runtime.grants.length === 0,
  "Disabled M3 must grant no runtime authority.",
);

const implementation = json("validation/evidence/m3/implementation-contracts.json");
requireValue(implementation.status === "implemented-contract-only", "Implementation evidence must not claim host qualification.");
requireValue(implementation.testCases.passed === true, "M3 focused contract suite is not recorded green.");
requireValue(implementation.testCases.productGateAndOciService >= 28, "M3 focused test count regressed.");
requireValue(implementation.testCases.durableCrashAndBackupSubset >= 38, "Durable crash subset count regressed.");

const host = json("validation/evidence/m3/runtime-host-windows.json");
requireValue(host.host.system === "windows", "Current committed host observation must identify Windows.");
requireValue(host.contractSuite.passed === true, "Host contract suite is not green.");
requireValue(host.qualified === false && host.status === "blocked", "Unqualified host must remain blocked.");
requireValue(host.approvedImageCount === 0, "Host observation cannot claim an approved image.");
requireValue(host.backends.docker.qualified === false, "Docker is not qualified by this observation.");
requireValue(host.backends.podman.qualified === false, "Podman is not qualified by this observation.");
requireValue(host.backends.docker.nativeConformancePassed === false, "Docker native conformance is not recorded.");
requireValue(host.backends.podman.nativeConformancePassed === false, "Podman native conformance is not recorded.");

const platforms = json("validation/evidence/m3/platform-matrix.json");
requireValue(
  JSON.stringify(platforms.requiredPlatforms) === JSON.stringify(["windows", "macos", "linux"]),
  "Platform requirement matrix drifted.",
);
requireValue(platforms.qualified === false, "Cross-platform runtime qualification is not complete.");
requireValue(platforms.platforms.every((item) => item.qualified === false), "No platform row may be promoted without native evidence.");

const power = json("validation/evidence/m3/power-loss-status.json");
requireValue(power.requiredCutPoints.length === 10, "Power-loss cut-point set regressed.");
requireValue(power.requiredRepetitionsPerCut === 10, "Power-loss repetition floor regressed.");
requireValue(power.requiredPhysicalCutRuns === 100, "Physical cut run floor drifted.");
requireValue(power.actualPhysicalCutRuns === 0 && power.abruptPowerCut === false, "Physical power loss must not be inferred.");
requireValue(power.processHardExitSurrogate.passed === true, "Process hard-exit subset must remain green.");
requireValue(power.processHardExitSurrogate.qualifiesAsPhysicalPowerLoss === false, "Process exit cannot qualify physical power loss.");
requireValue(power.qualified === false, "Power-loss gate cannot be promoted.");

const solver = json("validation/evidence/m3/solver-release-status.json");
const imageLock = json("validation/manifests/image-lock.json");
const corpus = json("validation/corpus/index.json");
const approvedImages = imageLock.images.filter((image) => image.releaseApproved === true);
const approvedBaselines = corpus.cases.filter((item) => item.expected !== null);
requireValue(solver.immutableImages.approvedCount === approvedImages.length, "M3 image count does not match image lock.");
requireValue(solver.numericalCorpus.approvedBaselines === approvedBaselines.length, "M3 corpus count does not match corpus index.");
requireValue(solver.sbom.approvedCount === 0, "No SBOM is approved.");
requireValue(solver.releaseApproved === false, "Solver release must remain blocked.");

const oci = read("backend/app/runtime/oci_backend.py").toString("utf8");
for (const marker of [
  "--network",
  "--cap-drop",
  "no-new-privileges",
  "--read-only",
  "65534:65534",
  "enforce_runtime_object_fence",
  "activation_manifest_sha256",
]) {
  requireValue(oci.includes(marker), "OCI security marker missing: " + marker);
}
const api = read("backend/app/service/local_api.py").toString("utf8");
for (const marker of ["peer-not-loopback", "host-not-loopback", "origin-not-allowed", "authentication-required"]) {
  requireValue(api.includes(marker), "Local API boundary marker missing: " + marker);
}
const application = read("backend/app/service/application.py").toString("utf8");
requireValue(application.includes("STARTUP_RECOVERY"), "Local service must recover before admission.");
requireValue(application.includes("NativeRestoreFloorStore"), "Local service must wire the OS anti-rollback floor.");
requireValue(application.includes("ProductDurableBrokerComposition"), "Local service must require the M3 product composition.");
requireValue(application.includes("current_schedule"), "Local service must validate configured schedules before admission.");
const composition = read("backend/app/service/product_composition.py").toString("utf8");
for (const marker of [
  "ProductActivationToken",
  "activation_manifest_sha256",
  "backend.name not in activation.approved_backends",
  "DurableRuntimeFenceActivator",
]) {
  requireValue(composition.includes(marker), "Product composition marker missing: " + marker);
}
const worker = read("backend/app/service/worker.py").toString("utf8");
requireValue(worker.includes("_control_gate"), "Cancellation control lane is missing.");
requireValue(worker.includes("requested_minimum_sequence"), "Native anti-rollback import gate is missing.");
for (const marker of ["renew_operation", "begin_maintenance", "mark_offline"]) {
  requireValue(worker.includes(marker), "Lifecycle arbitration marker missing: " + marker);
}
const credentials = read("backend/app/service/credentials.py").toString("utf8");
for (const marker of ["WindowsCredentialManagerStore", "MacOSKeychainCredentialStore", "SecretToolCredentialStore"]) {
  requireValue(credentials.includes(marker), "Native credential adapter missing: " + marker);
}
requireValue(application.includes("NativeCredentialStore"), "Product service must reject non-native credential stores.");
requireValue(credentials.includes("opentcad-secret-v1:"), "Secret Service byte encoding marker is missing.");
const scheduler = read("backend/app/service/scheduler.py").toString("utf8");
requireValue(scheduler.includes("self._failures"), "Scheduled backup failures must remain observable.");
requireValue(scheduler.includes("except AuthenticatedBackupError"), "Scheduled backup service failures must not terminate the loop.");

console.log("M3 entry-gate records are internally consistent and remain fail-closed.");
