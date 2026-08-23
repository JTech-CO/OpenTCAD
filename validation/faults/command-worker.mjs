import { spawn } from "node:child_process";

const PROTOCOL_VERSION = 1;
let activeJob = null;

function send(message) {
  if (process.connected) process.send(message);
}

function requirePositiveInteger(value, label, maximum) {
  if (!Number.isInteger(value) || value < 1 || value > maximum) {
    throw new RangeError(`${label} must be an integer from 1 through ${maximum}.`);
  }
  return value;
}

function validateCommand(command) {
  if (!command || typeof command !== "object" || Array.isArray(command)) {
    throw new TypeError("command must be an object.");
  }
  if (typeof command.executable !== "string" || command.executable.length === 0) {
    throw new TypeError("command.executable must be a non-empty string.");
  }
  if (!Array.isArray(command.args) || command.args.some((value) => typeof value !== "string")) {
    throw new TypeError("command.args must be an array of strings.");
  }
  if (command.cwd !== null && typeof command.cwd !== "string") {
    throw new TypeError("command.cwd must be a string or null.");
  }
  if (typeof command.stdinBase64 !== "string") {
    throw new TypeError("command.stdinBase64 must be a string.");
  }
  requirePositiveInteger(command.timeoutMs, "command.timeoutMs", 86_400_000);
  requirePositiveInteger(command.outputLimitBytes, "command.outputLimitBytes", 67_108_864);
  requirePositiveInteger(command.terminationGraceMs, "command.terminationGraceMs", 5_000);
  return command;
}

function terminate(child, signal) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return false;
  if (process.platform !== "win32" && child.pid) {
    try {
      process.kill(-child.pid, signal);
      return true;
    } catch {
      // Fall through to the direct child when its process group is already gone.
    }
  }
  try {
    return child.kill(signal);
  } catch {
    return false;
  }
}

function runCommand(jobId, rawCommand) {
  let command;
  try {
    command = validateCommand(rawCommand);
  } catch (error) {
    send({
      type: "result",
      protocolVersion: PROTOCOL_VERSION,
      jobId,
      result: {
        classification: "worker-error",
        exitCode: null,
        signal: null,
        durationMs: 0,
        spawnError: error instanceof Error ? error.message : String(error),
        outputLimitBytes: 0,
        observedOutputBytes: 0,
        capturedOutputBytes: 0,
        outputTruncated: false,
        stdoutBase64: "",
        stderrBase64: "",
      },
    });
    return;
  }

  const startedAt = Date.now();
  const stdout = [];
  const stderr = [];
  let observedOutputBytes = 0;
  let capturedOutputBytes = 0;
  let faultClassification = null;
  let spawnError = null;
  let timeoutTimer = null;
  let forceKillTimer = null;
  let settled = false;
  let child;

  const requestFault = (classification) => {
    if (faultClassification || settled) return;
    faultClassification = classification;
    terminate(child, "SIGTERM");
    forceKillTimer = setTimeout(() => terminate(child, "SIGKILL"), command.terminationGraceMs);
  };

  const capture = (target, chunk) => {
    const bytes = Buffer.from(chunk);
    observedOutputBytes += bytes.byteLength;
    const remaining = Math.max(0, command.outputLimitBytes - capturedOutputBytes);
    if (remaining > 0) {
      const kept = bytes.subarray(0, remaining);
      target.push(kept);
      capturedOutputBytes += kept.byteLength;
    }
    if (observedOutputBytes > command.outputLimitBytes) {
      requestFault("output-limit-exceeded");
    }
  };

  const finish = (exitCode, signal) => {
    if (settled) return;
    settled = true;
    if (timeoutTimer) clearTimeout(timeoutTimer);
    if (forceKillTimer) clearTimeout(forceKillTimer);
    const classification = faultClassification
      ?? (spawnError ? "spawn-failed" : exitCode === 0 ? "succeeded" : "nonzero-exit");
    activeJob = null;
    send({
      type: "result",
      protocolVersion: PROTOCOL_VERSION,
      jobId,
      result: {
        classification,
        exitCode,
        signal,
        durationMs: Date.now() - startedAt,
        spawnError,
        outputLimitBytes: command.outputLimitBytes,
        observedOutputBytes,
        capturedOutputBytes,
        outputTruncated: observedOutputBytes > capturedOutputBytes,
        stdoutBase64: Buffer.concat(stdout).toString("base64"),
        stderrBase64: Buffer.concat(stderr).toString("base64"),
      },
    });
  };

  try {
    child = spawn(command.executable, command.args, {
      cwd: command.cwd ?? undefined,
      env: process.env,
      shell: false,
      windowsHide: true,
      detached: process.platform !== "win32",
      stdio: ["pipe", "pipe", "pipe"],
    });
  } catch (error) {
    spawnError = error instanceof Error ? error.message : String(error);
    finish(null, null);
    return;
  }

  activeJob = { jobId, requestFault };
  timeoutTimer = setTimeout(() => requestFault("timed-out"), command.timeoutMs);
  child.stdout.on("data", (chunk) => capture(stdout, chunk));
  child.stderr.on("data", (chunk) => capture(stderr, chunk));
  child.on("error", (error) => {
    spawnError = error.message;
  });
  child.on("close", finish);
  child.stdin.on("error", () => {
    // Early stdin closure does not override the terminal classification.
  });
  child.stdin.end(Buffer.from(command.stdinBase64, "base64"));
}

process.on("message", (message) => {
  if (!message || message.protocolVersion !== PROTOCOL_VERSION) return;
  if (message.type === "run") {
    if (activeJob) {
      send({
        type: "protocol-error",
        protocolVersion: PROTOCOL_VERSION,
        jobId: message.jobId,
        error: "The worker accepts only one active job.",
      });
      return;
    }
    runCommand(message.jobId, message.command);
    return;
  }
  if (message.type === "cancel" && activeJob?.jobId === message.jobId) {
    activeJob.requestFault("cancelled");
    return;
  }
  if (message.type === "shutdown" && !activeJob) {
    process.exit(0);
  }
});

process.on("disconnect", () => {
  activeJob?.requestFault("cancelled");
  setTimeout(() => process.exit(1), 100).unref();
});

send({ type: "ready", protocolVersion: PROTOCOL_VERSION });
