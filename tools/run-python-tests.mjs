import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../", import.meta.url));
const supportedVersion = /^3\.(1[2-4])$/u;

function safeEnvironment() {
  const allowed = new Set(
    ["PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"]
      .map((name) => name.toUpperCase()),
  );
  return {
    ...Object.fromEntries(
      Object.entries(process.env).filter(
        ([name, value]) => allowed.has(name.toUpperCase()) && value !== undefined,
      ),
    ),
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONUTF8: "1",
  };
}

function candidates() {
  const explicit = process.env.OPENTCAD_PYTHON;
  if (explicit) return [{ executable: explicit, prefix: [], source: "OPENTCAD_PYTHON" }];
  if (process.platform === "win32") {
    return [
      { executable: "python", prefix: [], source: "PATH" },
      { executable: "py", prefix: ["-3.12"], source: "Python launcher 3.12" },
      { executable: "py", prefix: ["-3"], source: "Python launcher" },
    ];
  }
  return [
    { executable: "python3", prefix: [], source: "PATH" },
    { executable: "python", prefix: [], source: "PATH" },
  ];
}

function probe(candidate, environment) {
  const result = spawnSync(
    candidate.executable,
    [...candidate.prefix, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
    {
      cwd: repositoryRoot,
      env: environment,
      encoding: "utf8",
      shell: false,
      timeout: 10_000,
      windowsHide: true,
    },
  );
  if (result.error || result.status !== 0) return null;
  const version = result.stdout.trim();
  if (!supportedVersion.test(version)) return null;
  return { ...candidate, version };
}

const environment = safeEnvironment();
const python = candidates().map((candidate) => probe(candidate, environment)).find(Boolean);
if (!python) {
  console.error(
    "OpenTCAD runtime contract tests require Python 3.12, 3.13, or 3.14. "
      + "Set OPENTCAD_PYTHON to an approved interpreter when it is not on PATH.",
  );
  process.exitCode = 1;
} else {
  console.log(`Runtime contract tests: Python ${python.version} (${python.source})`);
  const result = spawnSync(
    python.executable,
    [
      ...python.prefix,
      "-m",
      "unittest",
      "discover",
      "-s",
      "backend/tests",
      "-p",
      "test_*.py",
      "-v",
    ],
    {
      cwd: repositoryRoot,
      env: environment,
      shell: false,
      stdio: "inherit",
      timeout: 120_000,
      windowsHide: true,
    },
  );
  if (result.error) {
    console.error(`Python contract test process failed: ${result.error.message}`);
    process.exitCode = 1;
  } else {
    process.exitCode = result.status ?? 1;
  }
}
