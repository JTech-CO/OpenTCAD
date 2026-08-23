import { fork } from "node:child_process";
import { fileURLToPath } from "node:url";

export const FAULT_CLASSIFICATIONS = Object.freeze([
  "timed-out",
  "cancelled",
  "output-limit-exceeded",
  "spawn-failed",
  "worker-crashed",
  "worker-error",
]);

const PROTOCOL_VERSION = 1;
const RESET_CLASSIFICATIONS = new Set(FAULT_CLASSIFICATIONS);
const DEFAULT_WORKER_MODULE = fileURLToPath(new URL("./command-worker.mjs", import.meta.url));
const SAFE_ENVIRONMENT_NAMES = new Set(
  [
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOME",
  ].map((name) => name.toUpperCase()),
);

function requirePositiveInteger(value, label, maximum) {
  if (!Number.isInteger(value) || value < 1 || value > maximum) {
    throw new RangeError(`${label} must be an integer from 1 through ${maximum}.`);
  }
  return value;
}

function isAbortSignal(value) {
  return (
    value !== null
    && typeof value === "object"
    && typeof value.aborted === "boolean"
    && typeof value.addEventListener === "function"
    && typeof value.removeEventListener === "function"
  );
}

function selectEnvironment(source, extraNames) {
  if (!Array.isArray(extraNames) || extraNames.some((name) => typeof name !== "string")) {
    throw new TypeError("environmentAllowlist must contain strings.");
  }
  const allowed = new Set([
    ...SAFE_ENVIRONMENT_NAMES,
    ...extraNames.map((name) => name.toUpperCase()),
  ]);
  return Object.fromEntries(
    Object.entries(source).filter(
      ([name, value]) => allowed.has(name.toUpperCase()) && value !== undefined,
    ),
  );
}

function validateCommand(command) {
  if (!command || typeof command !== "object" || Array.isArray(command)) {
    throw new TypeError("command must be an object.");
  }
  if (typeof command.executable !== "string" || command.executable.length === 0) {
    throw new TypeError("command.executable must be a non-empty string.");
  }
  const args = command.args ?? [];
  if (!Array.isArray(args) || args.some((value) => typeof value !== "string")) {
    throw new TypeError("command.args must be an array of strings.");
  }
  if (command.cwd !== undefined && typeof command.cwd !== "string") {
    throw new TypeError("command.cwd must be a string when supplied.");
  }
  const stdin = command.stdin ?? Buffer.alloc(0);
  if (!Buffer.isBuffer(stdin)) throw new TypeError("command.stdin must be a Buffer.");
  const timeoutMs = requirePositiveInteger(command.timeoutMs, "command.timeoutMs", 86_400_000);
  const outputLimitBytes = requirePositiveInteger(
    command.outputLimitBytes,
    "command.outputLimitBytes",
    67_108_864,
  );
  const terminationGraceMs = requirePositiveInteger(
    command.terminationGraceMs ?? 250,
    "command.terminationGraceMs",
    5_000,
  );
  return {
    executable: command.executable,
    args,
    cwd: command.cwd ?? null,
    stdinBase64: stdin.toString("base64"),
    timeoutMs,
    outputLimitBytes,
    terminationGraceMs,
  };
}

function emptyResult(classification) {
  return {
    classification,
    exitCode: null,
    signal: null,
    durationMs: 0,
    spawnError: null,
    outputLimitBytes: 0,
    observedOutputBytes: 0,
    capturedOutputBytes: 0,
    outputTruncated: false,
    stdout: Buffer.alloc(0),
    stderr: Buffer.alloc(0),
  };
}

function decodeResult(result) {
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
    stdout: Buffer.from(result.stdoutBase64, "base64"),
    stderr: Buffer.from(result.stderrBase64, "base64"),
  };
}

export class FaultPathSupervisor {
  constructor({
    workerModule = DEFAULT_WORKER_MODULE,
    environment = process.env,
    environmentAllowlist = [],
    startupTimeoutMs = 5_000,
    resetTimeoutMs = 1_000,
  } = {}) {
    if (typeof workerModule !== "string" || workerModule.length === 0) {
      throw new TypeError("workerModule must be a non-empty string.");
    }
    this.workerModule = workerModule;
    this.environment = selectEnvironment(environment, environmentAllowlist);
    this.startupTimeoutMs = requirePositiveInteger(startupTimeoutMs, "startupTimeoutMs", 30_000);
    this.resetTimeoutMs = requirePositiveInteger(resetTimeoutMs, "resetTimeoutMs", 10_000);
    this.worker = null;
    this.generation = 0;
    this.nextJobId = 1;
    this.activeJob = null;
  }

  async ensureWorker() {
    if (this.worker && this.worker.exitCode === null && this.worker.signalCode === null) {
      return this.worker;
    }

    this.generation += 1;
    const worker = fork(this.workerModule, [], {
      env: this.environment,
      execArgv: [],
      serialization: "json",
      silent: false,
      windowsHide: true,
      stdio: ["ignore", "ignore", "ignore", "ipc"],
    });
    this.worker = worker;

    try {
      await new Promise((resolvePromise, rejectPromise) => {
        const timer = setTimeout(
          () => rejectPromise(new Error("Fault-path worker startup timed out.")),
          this.startupTimeoutMs,
        );
        const cleanup = () => {
          clearTimeout(timer);
          worker.off("message", onMessage);
          worker.off("error", onError);
          worker.off("exit", onExit);
        };
        const onMessage = (message) => {
          if (message?.type !== "ready" || message.protocolVersion !== PROTOCOL_VERSION) return;
          cleanup();
          resolvePromise();
        };
        const onError = (error) => {
          cleanup();
          rejectPromise(error);
        };
        const onExit = (code, signal) => {
          cleanup();
          rejectPromise(
            new Error(`Fault-path worker exited during startup (${code ?? signal ?? "unknown"}).`),
          );
        };
        worker.on("message", onMessage);
        worker.once("error", onError);
        worker.once("exit", onExit);
      });
    } catch (error) {
      if (this.worker === worker) this.worker = null;
      worker.kill("SIGKILL");
      throw error;
    }

    return worker;
  }

  async resetWorker(worker) {
    if (this.worker === worker) this.worker = null;
    if (worker.exitCode !== null || worker.signalCode !== null) return;
    await new Promise((resolvePromise) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        clearTimeout(forceTimer);
        worker.off("exit", finish);
        resolvePromise();
      };
      const forceTimer = setTimeout(() => {
        worker.kill("SIGKILL");
        finish();
      }, this.resetTimeoutMs);
      worker.once("exit", finish);
      if (worker.connected) {
        worker.send({ type: "shutdown", protocolVersion: PROTOCOL_VERSION }, (error) => {
          if (error) worker.kill("SIGKILL");
        });
      } else {
        worker.kill("SIGKILL");
      }
    });
  }

  async run(command, { signal } = {}) {
    if (this.activeJob) throw new Error("The supervisor accepts only one active job.");
    if (signal !== undefined && !isAbortSignal(signal)) {
      throw new TypeError("signal must be an AbortSignal.");
    }
    const encodedCommand = validateCommand(command);
    if (signal?.aborted) {
      return {
        ...emptyResult("cancelled"),
        worker: { generation: null, pid: null, reset: false, restartReason: null },
      };
    }

    const reservation = Symbol("starting-fault-job");
    this.activeJob = reservation;
    let worker;
    try {
      worker = await this.ensureWorker();
    } catch (error) {
      if (this.activeJob === reservation) this.activeJob = null;
      throw error;
    }
    const generation = this.generation;
    const pid = worker.pid;
    const jobId = `fault-job-${this.nextJobId}`;
    this.nextJobId += 1;
    this.activeJob = jobId;

    return new Promise((resolvePromise) => {
      let settled = false;
      const cleanup = () => {
        worker.off("message", onMessage);
        worker.off("error", onError);
        worker.off("exit", onExit);
        signal?.removeEventListener("abort", onAbort);
      };
      const finish = async (result, reset) => {
        if (settled) return;
        settled = true;
        cleanup();
        this.activeJob = null;
        if (reset) await this.resetWorker(worker);
        resolvePromise({
          ...result,
          worker: {
            generation,
            pid,
            reset,
            restartReason: reset ? result.classification : null,
          },
        });
      };
      const onMessage = (message) => {
        if (message?.jobId !== jobId) return;
        if (message.type === "protocol-error") {
          void finish(
            { ...emptyResult("worker-error"), spawnError: message.error ?? "Worker protocol error." },
            true,
          );
          return;
        }
        if (message.type !== "result" || message.protocolVersion !== PROTOCOL_VERSION) return;
        const result = decodeResult(message.result);
        void finish(result, RESET_CLASSIFICATIONS.has(result.classification));
      };
      const onError = (error) => {
        void finish({ ...emptyResult("worker-crashed"), spawnError: error.message }, true);
      };
      const onExit = (code, workerSignal) => {
        if (this.worker === worker) this.worker = null;
        void finish(
          {
            ...emptyResult("worker-crashed"),
            signal: workerSignal,
            spawnError: `Worker exited before returning a result (${code ?? workerSignal ?? "unknown"}).`,
          },
          true,
        );
      };
      const onAbort = () => {
        if (worker.connected) {
          worker.send({ type: "cancel", protocolVersion: PROTOCOL_VERSION, jobId }, () => {});
        }
      };

      worker.on("message", onMessage);
      worker.once("error", onError);
      worker.once("exit", onExit);
      signal?.addEventListener("abort", onAbort, { once: true });
      worker.send(
        { type: "run", protocolVersion: PROTOCOL_VERSION, jobId, command: encodedCommand },
        (error) => {
          if (error) onError(error);
        },
      );
      if (signal?.aborted) onAbort();
    });
  }

  async close() {
    if (this.activeJob) throw new Error("Cannot close the supervisor while a job is active.");
    if (this.worker) await this.resetWorker(this.worker);
  }
}
