import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { FaultPathSupervisor } from "./supervisor.mjs";

const fixturePath = fileURLToPath(new URL("./fixtures/fault-command.mjs", import.meta.url));

function fixtureJob(mode, value = "", overrides = {}) {
  return {
    executable: process.execPath,
    args: [fixturePath, mode, value],
    timeoutMs: 5_000,
    outputLimitBytes: 16_384,
    terminationGraceMs: 100,
    ...overrides,
  };
}

test("healthy commands reuse one supervised worker", async (context) => {
  const supervisor = new FaultPathSupervisor();
  context.after(() => supervisor.close());

  const first = await supervisor.run(fixtureJob("echo", "alpha"));
  const second = await supervisor.run(fixtureJob("stderr", "beta"));

  assert.equal(first.classification, "succeeded");
  assert.equal(first.stdout.toString("utf8"), "alpha");
  assert.equal(second.classification, "succeeded");
  assert.equal(second.stderr.toString("utf8"), "beta");
  assert.equal(second.worker.generation, first.worker.generation);
  assert.equal(second.worker.pid, first.worker.pid);
  assert.equal(first.worker.reset, false);
  assert.equal(second.worker.reset, false);
});

test("timeout resets the worker before the next job", async (context) => {
  const supervisor = new FaultPathSupervisor();
  context.after(() => supervisor.close());

  const timedOut = await supervisor.run(fixtureJob("hang", "", { timeoutMs: 150 }));
  const recovered = await supervisor.run(fixtureJob("echo", "recovered"));

  assert.equal(timedOut.classification, "timed-out");
  assert.equal(timedOut.worker.reset, true);
  assert.equal(timedOut.worker.restartReason, "timed-out");
  assert.equal(recovered.classification, "succeeded");
  assert.equal(recovered.stdout.toString("utf8"), "recovered");
  assert.equal(recovered.worker.generation, timedOut.worker.generation + 1);
  assert.notEqual(recovered.worker.pid, timedOut.worker.pid);
});

test("AbortSignal cancellation resets a running worker", async (context) => {
  const supervisor = new FaultPathSupervisor();
  context.after(() => supervisor.close());
  const warm = await supervisor.run(fixtureJob("echo", "warm"));
  const controller = new AbortController();

  const pending = supervisor.run(fixtureJob("hang"), { signal: controller.signal });
  setTimeout(() => controller.abort(), 75);
  const cancelled = await pending;
  const recovered = await supervisor.run(fixtureJob("echo", "after-cancel"));

  assert.equal(cancelled.classification, "cancelled");
  assert.equal(cancelled.worker.generation, warm.worker.generation);
  assert.equal(cancelled.worker.reset, true);
  assert.equal(recovered.classification, "succeeded");
  assert.equal(recovered.worker.generation, cancelled.worker.generation + 1);
  assert.notEqual(recovered.worker.pid, cancelled.worker.pid);
});

test("combined output cap truncates capture, classifies the fault, and resets", async (context) => {
  const supervisor = new FaultPathSupervisor();
  context.after(() => supervisor.close());
  await supervisor.run(fixtureJob("echo", "warm"));

  const limited = await supervisor.run(
    fixtureJob("mixed-output", "1536", { outputLimitBytes: 1_024 }),
  );
  const recovered = await supervisor.run(fixtureJob("echo", "after-output-limit"));

  assert.equal(limited.classification, "output-limit-exceeded");
  assert.equal(limited.outputLimitBytes, 1_024);
  assert.ok(limited.observedOutputBytes > limited.outputLimitBytes);
  assert.equal(limited.capturedOutputBytes, 1_024);
  assert.equal(limited.stdout.byteLength + limited.stderr.byteLength, 1_024);
  assert.ok(limited.stdout.byteLength > 0);
  assert.ok(limited.stderr.byteLength > 0);
  assert.equal(limited.outputTruncated, true);
  assert.equal(limited.worker.reset, true);
  assert.equal(recovered.classification, "succeeded");
  assert.equal(recovered.worker.generation, limited.worker.generation + 1);
});

test("invalid requests and concurrent jobs fail closed", async (context) => {
  const supervisor = new FaultPathSupervisor();
  context.after(() => supervisor.close());

  await assert.rejects(
    supervisor.run(fixtureJob("echo", "", { outputLimitBytes: 0 })),
    /outputLimitBytes/,
  );

  const controller = new AbortController();
  const active = supervisor.run(fixtureJob("hang"), { signal: controller.signal });
  await assert.rejects(supervisor.run(fixtureJob("echo", "blocked")), /one active job/);
  controller.abort();
  assert.equal((await active).classification, "cancelled");
});
