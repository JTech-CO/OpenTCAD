import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";

import {
  allowedEnvironment,
  collectFileEvidence,
  countLinePrefixes,
  evaluateLogPolicy,
  evaluateRequiredProfile,
  pathIsWithin,
  requireSafeRelativePath,
  runCapturedCommand,
  sha256Hex,
  summarizeArtifactRepeatability,
} from "./observation.mjs";

test("file evidence hashes exact bytes and rejects root escapes", async (context) => {
  const root = await mkdtemp(join(tmpdir(), "opentcad-observation-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  await mkdir(join(root, "artifacts"));
  const bytes = Buffer.from("c 1\r\nt 1\r\n", "utf8");
  await writeFile(join(root, "artifacts", "result.str"), bytes);

  const evidence = await collectFileEvidence(root, {
    id: "structure",
    kind: "structure",
    relativePath: "artifacts/result.str",
    required: true,
  });

  assert.equal(evidence.present, true);
  assert.equal(evidence.bytes, bytes.byteLength);
  assert.equal(evidence.sha256, sha256Hex(bytes));
  assert.throws(() => requireSafeRelativePath("../secret", "fixture"), /stay within/);
  assert.equal(pathIsWithin(root, resolve(root, "artifacts", "result.str")), true);
  assert.equal(pathIsWithin(root, resolve(root, "..", "outside")), false);
});

test("line-prefix metrics count topology records without normalizing the artifact", () => {
  const counts = countLinePrefixes("v header\nc 1\nc 2\nr 1\nt 1\nt 2\nb 1\n", {
    nodes: "c ",
    regions: "r ",
    elements: "t ",
    boundaries: "b ",
  });

  assert.deepEqual(counts, { nodes: 2, regions: 1, elements: 2, boundaries: 1 });
});

test("declared log failures override a zero exit code", () => {
  const policy = {
    mode: "fail-on-match",
    failurePatterns: [
      { id: "input-error", stream: "stderr", substring: "input error" },
      { id: "panic", stream: "both", substring: "panic" },
    ],
  };
  const clean = evaluateLogPolicy("completed", "", policy);
  const failed = evaluateLogPolicy("panic after output", "input error\ninput error\n", policy);

  assert.equal(clean.pass, true);
  assert.equal(failed.pass, false);
  assert.deepEqual(failed.findings, [
    { id: "input-error", stream: "stderr", count: 2 },
    { id: "panic", stream: "stdout", count: 1 },
  ]);
});

test("required profile distinguishes a conforming Podman host from Docker Desktop", () => {
  const required = {
    runtime: "podman",
    operatingSystem: "linux",
    architecture: "amd64",
    rootless: true,
  };
  const conforming = evaluateRequiredProfile(required, {
    runtime: "podman",
    operatingSystem: "Linux",
    architecture: "x86_64",
    rootless: true,
  });
  const docker = evaluateRequiredProfile(required, {
    runtime: "docker",
    operatingSystem: "linux",
    architecture: "amd64",
    rootless: false,
  });

  assert.equal(conforming.meetsRequiredProfile, true);
  assert.equal(docker.meetsRequiredProfile, false);
  assert.deepEqual(docker.mismatches, ["runtime", "rootless"]);
});

test("environment filtering excludes undeclared values", () => {
  const filtered = allowedEnvironment(
    { PATH: "runtime", SECRET_TOKEN: "hidden", CUSTOM_SAFE: "visible" },
    ["CUSTOM_SAFE"],
  );
  assert.deepEqual(filtered, { PATH: "runtime", CUSTOM_SAFE: "visible" });
});

test("captured commands preserve stdin and classify success and timeout", async () => {
  const environment = allowedEnvironment(process.env);
  const echoed = await runCapturedCommand({
    executable: process.execPath,
    args: ["-e", "process.stdin.pipe(process.stdout)"],
    stdin: Buffer.from([0, 1, 2, 10, 255]),
    timeoutMs: 5_000,
    environment,
  });
  assert.equal(echoed.classification, "succeeded");
  assert.deepEqual(echoed.stdout, Buffer.from([0, 1, 2, 10, 255]));

  const timedOut = await runCapturedCommand({
    executable: process.execPath,
    args: ["-e", "setInterval(() => {}, 1000)"],
    timeoutMs: 100,
    environment,
  });
  assert.equal(timedOut.classification, "timed-out");
  assert.equal(timedOut.timedOut, true);
});

test("artifact repeatability requires every run and one exact hash", () => {
  const descriptors = [{ id: "structure", required: true }];
  const stable = summarizeArtifactRepeatability(
    [
      { artifacts: [{ id: "structure", present: true, sha256: "a" }] },
      { artifacts: [{ id: "structure", present: true, sha256: "a" }] },
    ],
    descriptors,
  );
  const drifted = summarizeArtifactRepeatability(
    [
      { artifacts: [{ id: "structure", present: true, sha256: "a" }] },
      { artifacts: [{ id: "structure", present: true, sha256: "b" }] },
    ],
    descriptors,
  );

  assert.equal(stable[0].exactlyRepeatable, true);
  assert.equal(drifted[0].exactlyRepeatable, false);
});
