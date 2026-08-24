import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  buildCreateArguments,
  evaluateContainerPolicy,
  evaluateProcessStatus,
  evaluateScenarioOutcome,
  normalizeRuntimeProfile,
  parseOrphanQuery,
  runtimeCommandArguments,
  validateOciFaultPlan,
} from "./oci-fault-observation.mjs";

const plan = validateOciFaultPlan(
  JSON.parse(
    await readFile(new URL("../plans/m0-oci-fault-matrix.json", import.meta.url), "utf8"),
  ),
);

function inspectFixture(runtime) {
  return {
    ImageDigest: runtime === "podman" ? plan.image.indexDigest : undefined,
    ImageManifestDescriptor:
      runtime === "docker" ? { digest: plan.image.platformManifestDigest } : undefined,
    Mounts: [],
    Config: {
      Image: plan.image.reference,
      User: plan.policy.user,
      StopTimeout: plan.policy.stopTimeoutSeconds,
      CreateCommand:
        runtime === "podman"
          ? ["podman", "create", "--cap-drop", "ALL", "--read-only-tmpfs=false"]
          : undefined,
    },
    HostConfig: {
      AutoRemove: false,
      Binds: runtime === "docker" ? null : [],
      CapDrop: runtime === "docker" ? ["ALL"] : ["CAP_CHOWN", "CAP_KILL"],
      Memory: plan.policy.memoryBytes,
      NanoCpus: plan.policy.cpus * 1_000_000_000,
      NetworkMode: "none",
      PidsLimit: plan.policy.pidsLimit,
      Privileged: false,
      ReadonlyRootfs: true,
      RestartPolicy: { Name: "no" },
      SecurityOpt: ["no-new-privileges"],
    },
  };
}

test("reviewed OCI fault plan is non-promoting and command-allowlisted", () => {
  assert.equal(plan.baselinePromotionAllowed, false);
  assert.equal(plan.distributionAllowed, false);
  assert.equal(plan.mixedLoop.count, 20);

  const arbitrary = structuredClone(plan);
  arbitrary.scenarios[0].command = ["/bin/sh", "-c", "id"];
  assert.throws(() => validateOciFaultPlan(arbitrary), /allowlist/);

  const weaker = structuredClone(plan);
  weaker.policy.network = "bridge";
  assert.throws(() => validateOciFaultPlan(weaker), /policy drifted/);

  const writableTmpfs = structuredClone(plan);
  writableTmpfs.policy.writableTemporaryFilesystems = true;
  assert.throws(() => validateOciFaultPlan(writableTmpfs), /policy drifted/);
});

test("Docker and Podman create mappings retain every reviewed policy control", () => {
  for (const runtime of ["docker", "podman"]) {
    const args = buildCreateArguments(runtime, plan, {
      name: `opentcad-fault-${runtime}-001`,
      caseId: "timeout",
      observationValue: `m0-oci-fault-${runtime}`,
      command: ["/usr/bin/sleep", "30"],
    });
    assert.equal(args[0], "create");
    assert.ok(args.includes("--network"));
    assert.ok(args.includes("none"));
    assert.ok(args.includes("--cap-drop"));
    assert.ok(args.includes("ALL"));
    assert.ok(args.includes("--security-opt"));
    assert.ok(args.includes("no-new-privileges"));
    assert.ok(args.includes("--read-only"));
    assert.equal(args.includes("--read-only-tmpfs=false"), runtime === "podman");
    assert.ok(args.includes("65534:65534"));
    assert.ok(args.includes("32"));
    assert.ok(args.includes(String(plan.policy.memoryBytes)));
    assert.ok(args.includes(String(plan.policy.cpus)));
    assert.ok(args.includes(plan.image.reference));
    assert.equal(args.includes("--mount"), false);
    assert.equal(args.includes("--volume"), false);
    assert.equal(args.includes("--privileged"), false);
    assert.deepEqual(args.slice(-2), ["/usr/bin/sleep", "30"]);
  }
});

test("backend command mappings keep Docker and Podman formatting separate", () => {
  assert.deepEqual(runtimeCommandArguments("docker", "version"), [
    "version",
    "--format",
    "{{json .}}",
  ]);
  assert.deepEqual(runtimeCommandArguments("podman", "version"), [
    "version",
    "--format",
    "json",
  ]);
  assert.deepEqual(runtimeCommandArguments("docker", "start", "job"), [
    "start",
    "--attach",
    "job",
  ]);
  assert.match(
    runtimeCommandArguments(
      "podman",
      "orphan-query",
      "label=org.opentcad.observation=value",
    ).join(" "),
    /--format json/u,
  );
});

test("policy evaluation accepts the observed Docker and Podman inspect shapes", () => {
  for (const runtime of ["docker", "podman"]) {
    const result = evaluateContainerPolicy(runtime, inspectFixture(runtime), plan);
    assert.equal(result.pass, true);
    assert.ok(Object.values(result.checks).every(Boolean));
  }

  const drifted = inspectFixture("docker");
  drifted.HostConfig.NetworkMode = "bridge";
  const result = evaluateContainerPolicy("docker", drifted, plan);
  assert.equal(result.pass, false);
  assert.equal(result.checks.networkNone, false);
});

test("process status requires zero effective capabilities, NNP, and uid 65534", () => {
  const accepted = evaluateProcessStatus(
    "Name:\ttest\nUid:\t65534\t65534\t65534\t65534\nCapEff:\t0000000000000000\nNoNewPrivs:\t1\n",
  );
  const privileged = evaluateProcessStatus(
    "Uid:\t0\t0\t0\t0\nCapEff:\t00000000a80425fb\nNoNewPrivs:\t0\n",
  );
  assert.equal(accepted.pass, true);
  assert.equal(privileged.pass, false);
});

test("scenario evaluation separates container exits from injected supervisor faults", () => {
  const nonzero = evaluateScenarioOutcome(
    plan.scenarios.find(({ id }) => id === "declared-nonzero-exit"),
    { classification: "succeeded" },
    { State: { Running: false, ExitCode: 1 } },
    plan,
  );
  assert.equal(nonzero.pass, true);

  const output = evaluateScenarioOutcome(
    plan.scenarios.find(({ id }) => id === "output-bomb"),
    {
      classification: "output-limit-exceeded",
      worker: { reset: true },
      outputTruncated: true,
      capturedOutputBytes: plan.limits.outputBombLimitBytes,
      observedOutputBytes: plan.limits.outputBombLimitBytes + 1,
    },
    { State: { Running: true, ExitCode: 0 } },
    plan,
  );
  assert.equal(output.pass, true);
});

test("orphan parsing and profile normalization retain backend differences", () => {
  assert.equal(parseOrphanQuery("docker", Buffer.from("", "utf8")).length, 0);
  assert.equal(
    parseOrphanQuery("docker", Buffer.from('{"ID":"abc"}\n{"ID":"def"}\n', "utf8"))
      .length,
    2,
  );
  assert.equal(parseOrphanQuery("podman", Buffer.from("[]\n", "utf8")).length, 0);

  const docker = normalizeRuntimeProfile(
    "docker",
    { Server: { Version: "29", Os: "linux", Arch: "amd64" } },
    { KernelVersion: "kernel", CgroupVersion: "2", CgroupDriver: "cgroupfs" },
  );
  const podman = normalizeRuntimeProfile(
    "podman",
    { Client: { Version: "5" } },
    {
      host: {
        os: "linux",
        arch: "x86_64",
        kernel: "kernel",
        cgroupVersion: "v2",
        cgroupManager: "cgroupfs",
        security: { rootless: true },
      },
    },
  );
  assert.equal(docker.rootless, false);
  assert.equal(podman.rootless, true);
  assert.equal(podman.architecture, "amd64");
});
