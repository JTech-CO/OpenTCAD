import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { lstat, readFile, realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep } from "node:path";

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
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "CONTAINER_HOST",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
  ].map((name) => name.toUpperCase()),
);

function ensureString(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    throw new TypeError(`${label} must be a non-empty string.`);
  }
  return value;
}

export function requireSafeRelativePath(value, label = "path") {
  ensureString(value, label);
  if (isAbsolute(value) || value.split(/[\\/]+/u).includes("..")) {
    throw new Error(`${label} must stay within its declared root.`);
  }
  return value;
}

export function pathIsWithin(parent, candidate) {
  const fromParent = relative(resolve(parent), resolve(candidate));
  return fromParent === "" || (!fromParent.startsWith(`..${sep}`) && fromParent !== "..");
}

export function sha256Hex(value) {
  return createHash("sha256").update(value).digest("hex");
}

export async function collectFileEvidence(root, descriptor) {
  const relativePath = requireSafeRelativePath(descriptor.relativePath, `${descriptor.id}.relativePath`);
  const absolutePath = resolve(root, relativePath);
  if (!pathIsWithin(root, absolutePath)) {
    throw new Error(`${descriptor.id} resolves outside its declared root.`);
  }

  try {
    const fileStat = await lstat(absolutePath);
    if (fileStat.isSymbolicLink()) throw new Error(`${descriptor.id} must not be a symbolic link.`);
    if (!fileStat.isFile()) throw new Error(`${descriptor.id} is not a regular file.`);
    const resolvedRoot = await realpath(root);
    const resolvedFile = await realpath(absolutePath);
    if (!pathIsWithin(resolvedRoot, resolvedFile)) {
      throw new Error(`${descriptor.id} resolves outside its declared root.`);
    }
    const bytes = await readFile(resolvedFile);
    return {
      id: ensureString(descriptor.id, "artifact id"),
      kind: ensureString(descriptor.kind, `${descriptor.id}.kind`),
      relativePath,
      required: descriptor.required === true,
      present: true,
      bytes: bytes.byteLength,
      sha256: sha256Hex(bytes),
    };
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    return {
      id: ensureString(descriptor.id, "artifact id"),
      kind: ensureString(descriptor.kind, `${descriptor.id}.kind`),
      relativePath,
      required: descriptor.required === true,
      present: false,
      bytes: null,
      sha256: null,
    };
  }
}

export function countLinePrefixes(value, prefixes) {
  const text = Buffer.isBuffer(value) ? value.toString("utf8") : String(value);
  if (!prefixes || typeof prefixes !== "object" || Array.isArray(prefixes)) {
    throw new TypeError("prefixes must be an object.");
  }

  const entries = Object.entries(prefixes);
  if (entries.length === 0) throw new Error("prefixes must not be empty.");
  entries.forEach(([metric, prefix]) => {
    ensureString(metric, "metric name");
    ensureString(prefix, `prefix for ${metric}`);
  });

  const counts = Object.fromEntries(entries.map(([metric]) => [metric, 0]));
  for (const line of text.split(/\r?\n/u)) {
    for (const [metric, prefix] of entries) {
      if (line.startsWith(prefix)) counts[metric] += 1;
    }
  }
  return counts;
}

export function evaluateLogPolicy(stdout, stderr, policy) {
  if (!policy || policy.mode !== "fail-on-match") {
    throw new Error("log policy mode must be fail-on-match.");
  }
  if (!Array.isArray(policy.failurePatterns) || policy.failurePatterns.length === 0) {
    throw new Error("log policy must declare failure patterns.");
  }

  const streams = {
    stdout: Buffer.isBuffer(stdout) ? stdout.toString("utf8") : String(stdout),
    stderr: Buffer.isBuffer(stderr) ? stderr.toString("utf8") : String(stderr),
  };
  const findings = [];
  for (const pattern of policy.failurePatterns) {
    ensureString(pattern.id, "log failure pattern id");
    if (!["stdout", "stderr", "both"].includes(pattern.stream)) {
      throw new Error(`Unknown log stream for ${pattern.id}.`);
    }
    const substring = ensureString(pattern.substring, `substring for ${pattern.id}`);
    const selectedStreams = pattern.stream === "both" ? ["stdout", "stderr"] : [pattern.stream];
    for (const stream of selectedStreams) {
      let count = 0;
      let cursor = 0;
      while (true) {
        const match = streams[stream].indexOf(substring, cursor);
        if (match < 0) break;
        count += 1;
        cursor = match + substring.length;
      }
      if (count > 0) findings.push({ id: pattern.id, stream, count });
    }
  }

  return {
    mode: policy.mode,
    pass: findings.length === 0,
    checkedPatternIds: policy.failurePatterns.map(({ id }) => id),
    findings,
  };
}

export function normalizeArchitecture(value) {
  const normalized = String(value ?? "").toLowerCase();
  if (["x86_64", "x64"].includes(normalized)) return "amd64";
  if (["aarch64", "arm64/v8"].includes(normalized)) return "arm64";
  return normalized;
}

export function evaluateRequiredProfile(required, observed) {
  const checks = {
    runtime: required.runtime === observed.runtime,
    operatingSystem:
      String(required.operatingSystem).toLowerCase() === String(observed.operatingSystem).toLowerCase(),
    architecture:
      normalizeArchitecture(required.architecture) === normalizeArchitecture(observed.architecture),
    rootless: required.rootless === observed.rootless,
  };

  return {
    meetsRequiredProfile: Object.values(checks).every(Boolean),
    checks,
    mismatches: Object.entries(checks)
      .filter(([, matches]) => !matches)
      .map(([field]) => field),
  };
}

export function allowedEnvironment(source = process.env, extraNames = []) {
  if (!Array.isArray(extraNames) || extraNames.some((name) => typeof name !== "string")) {
    throw new TypeError("extra environment names must be strings.");
  }
  const allowed = new Set([...SAFE_ENVIRONMENT_NAMES, ...extraNames.map((name) => name.toUpperCase())]);
  return Object.fromEntries(
    Object.entries(source).filter(([name, value]) => allowed.has(name.toUpperCase()) && value !== undefined),
  );
}

export function runCapturedCommand({
  executable,
  args,
  cwd,
  stdin = Buffer.alloc(0),
  timeoutMs,
  environment = allowedEnvironment(),
}) {
  ensureString(executable, "executable");
  if (!Array.isArray(args) || args.some((argument) => typeof argument !== "string")) {
    throw new TypeError("args must be an array of strings.");
  }
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1) {
    throw new RangeError("timeoutMs must be a positive integer.");
  }

  return new Promise((resolvePromise) => {
    const startedAt = Date.now();
    const stdout = [];
    const stderr = [];
    let timedOut = false;
    let spawnError = null;
    let settled = false;
    let forceKillTimer = null;

    const child = spawn(executable, args, {
      cwd,
      env: environment,
      shell: false,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
      forceKillTimer = setTimeout(() => child.kill("SIGKILL"), 5_000);
    }, timeoutMs);

    child.stdout.on("data", (chunk) => stdout.push(Buffer.from(chunk)));
    child.stderr.on("data", (chunk) => stderr.push(Buffer.from(chunk)));
    child.on("error", (error) => {
      spawnError = error;
    });
    child.on("close", (exitCode, signal) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (forceKillTimer) clearTimeout(forceKillTimer);
      const durationMs = Date.now() - startedAt;
      const classification = spawnError
        ? "spawn-failed"
        : timedOut
          ? "timed-out"
          : exitCode === 0
            ? "succeeded"
            : "nonzero-exit";

      resolvePromise({
        classification,
        exitCode,
        signal,
        timedOut,
        durationMs,
        stdout: Buffer.concat(stdout),
        stderr: Buffer.concat(stderr),
        spawnError: spawnError?.message ?? null,
      });
    });

    child.stdin.on("error", () => {
      // A process may close stdin before exit. Its exit classification remains authoritative.
    });
    child.stdin.end(stdin);
  });
}

export function summarizeArtifactRepeatability(runs, descriptors) {
  return descriptors.map(({ id, required }) => {
    const observations = runs
      .map((run) => run.artifacts.find((artifact) => artifact.id === id))
      .filter(Boolean);
    const hashes = observations.filter(({ present }) => present).map(({ sha256 }) => sha256);
    const uniqueHashes = [...new Set(hashes)].sort();
    const allRunsPresent = observations.length === runs.length && hashes.length === runs.length;

    return {
      artifactId: id,
      required: required === true,
      observedRuns: hashes.length,
      expectedRuns: runs.length,
      allRunsPresent,
      uniqueHashes,
      exactlyRepeatable: allRunsPresent && uniqueHashes.length === 1,
    };
  });
}
