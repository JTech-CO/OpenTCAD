import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
const python = process.env.OPENTCAD_LAB_PYTHON || path.join(root, ".venv-mvp", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
if (!existsSync(python)) {
  console.error("Create .venv-mvp and install backend/app/experimental/requirements.txt. See docs/en/mvp-laboratory.md.");
  process.exit(1);
}
const test = process.argv.includes("--test");
const child = spawn(python, test ? ["-m", "unittest", "backend.tests.experimental.test_numerical", "backend.tests.experimental.test_mos", "backend.tests.experimental.test_process_mesh", "-v"]
  : ["-m", "backend.app.experimental.service", "--enable-experimental-devsim", ...process.argv.slice(2)], {
  cwd: root, shell: false, windowsHide: true, stdio: "inherit",
  env: { ...process.env, PYTHONUTF8: "1", ...(test ? { OPENTCAD_TEST_DEVSIM: "1" } : {}) },
});
child.on("error", () => { console.error("Experimental Python process could not start."); process.exitCode = 1; });
child.on("exit", code => { process.exitCode = code ?? 1; });
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
