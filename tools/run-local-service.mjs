import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const repositoryRoot = fileURLToPath(new URL("../", import.meta.url));
const supportedVersion = /^3\.(1[2-4])$/u;
const commands = new Set(["doctor", "preview", "serve"]);

function safeEnvironment() {
  const allowed = new Set(
    [
      "PATH",
      "PATHEXT",
      "SYSTEMROOT",
      "WINDIR",
      "TEMP",
      "TMP",
      "HOME",
      "USERPROFILE",
      "LOCALAPPDATA",
      "APPDATA",
      "XDG_CONFIG_HOME",
      "XDG_STATE_HOME",
      "XDG_RUNTIME_DIR",
      "DBUS_SESSION_BUS_ADDRESS",
      "DOCKER_CONFIG",
      "CONTAINERS_CONF",
      "CONTAINERS_STORAGE_CONF",
    ].map((name) => name.toUpperCase()),
  );
  return {
    ...Object.fromEntries(
      Object.entries(process.env).filter(
        ([name, value]) =>
          allowed.has(name.toUpperCase()) && value !== undefined,
      ),
    ),
    PYTHONDONTWRITEBYTECODE: "1",
    PYTHONUTF8: "1",
  };
}

function candidates() {
  const explicit = process.env.OPENTCAD_PYTHON;
  if (explicit) {
    return [
      {
        executable: explicit,
        prefix: [],
        source: "OPENTCAD_PYTHON",
      },
    ];
  }
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
    [
      ...candidate.prefix,
      "-c",
      "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
    ],
    {
      cwd: repositoryRoot,
      env: environment,
      encoding: "utf8",
      shell: false,
      timeout: 10_000,
      windowsHide: true,
    },
  );
  if (result.error || result.status !== 0) {
    return null;
  }
  const version = result.stdout.trim();
  return supportedVersion.test(version)
    ? { ...candidate, version }
    : null;
}

const arguments_ = process.argv.slice(2);
if (!commands.has(arguments_[0])) {
  console.error("Usage: run-local-service.mjs <doctor|preview|serve> [options]");
  process.exitCode = 2;
} else {
  const environment = safeEnvironment();
  const python = candidates()
    .map((candidate) => probe(candidate, environment))
    .find(Boolean);
  if (!python) {
    console.error(
      "OpenTCAD local service requires Python 3.12, 3.13, or 3.14. "
        + "Set OPENTCAD_PYTHON to an approved interpreter when it is not on PATH.",
    );
    process.exitCode = 1;
  } else {
    const child = spawn(
      python.executable,
      [
        ...python.prefix,
        "-m",
        "backend.app.service",
        ...arguments_,
      ],
      {
        cwd: repositoryRoot,
        env: environment,
        shell: false,
        stdio: "inherit",
        windowsHide: true,
      },
    );
    const forwardedSignals =
      process.platform === "win32"
        ? ["SIGTERM"]
        : ["SIGINT", "SIGTERM", "SIGHUP"];
    const handlers = new Map(
      forwardedSignals.map((signal) => [
        signal,
        () => {
          if (child.exitCode === null && child.signalCode === null) {
            child.kill(signal);
          }
        },
      ]),
    );
    for (const [signal, handler] of handlers) {
      process.on(signal, handler);
    }
    child.on("error", (error) => {
      console.error(`OpenTCAD local service failed: ${error.message}`);
      process.exitCode = 1;
    });
    child.on("exit", (code, signal) => {
      for (const [name, handler] of handlers) {
        process.off(name, handler);
      }
      process.exitCode =
        code
        ?? (signal === "SIGINT"
          ? 130
          : signal === "SIGTERM"
            ? 143
            : 1);
    });
  }
}
