import { spawnSync } from "node:child_process";
import { closeSync, mkdirSync, openSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import path from "node:path";
import os from "node:os";

const root = fileURLToPath(new URL("../", import.meta.url));
const git = (...args) => {
  const result = spawnSync("git", args, {cwd: root, encoding: "utf8", windowsHide: true});
  if (result.status !== 0) throw new Error("git-check-failed");
  return result.stdout.trim();
};
const sha = data => createHash("sha256").update(data).digest("hex");
const args = process.argv.slice(2);
if (process.platform !== "win32" || args.length !== 2 || args[0] !== "--output" || !path.isAbsolute(args[1]) || !process.env.npm_execpath) {
  throw new Error("Use npm run accept:windows -- --output ABSOLUTE_NEW_DIRECTORY on Windows");
}
const revision = git("rev-parse", "HEAD");
if (git("status", "--porcelain")) throw new Error("Acceptance requires a clean checkout");
const output = args[1];
mkdirSync(output, {recursive: false});
const report = {schemaVersion: 1, revision, startedAt: new Date().toISOString(),
  host: {platform: process.platform, architecture: os.arch(), release: os.release(), node: process.version},
  classification: "automated-windows-acceptance", dedicatedHostAttestedByOwner: false,
  steps: [], releaseApproved: false, m3Approved: false};
for (const script of ["check", "local:mvp", "test:mvp:solver"]) {
  const log = script.replaceAll(":", "-") + ".log";
  console.log(`Acceptance: ${script}`);
  const fd = openSync(path.join(output, log), "wx");
  let result;
  try {
    result = spawnSync(process.execPath, [process.env.npm_execpath, "run", script, ...(script === "local:mvp" ? ["--", "doctor"] : [])],
      {cwd: root, env: {...process.env, OPENTCAD_NUMERICAL_EVIDENCE_DIR: output},
        stdio: ["ignore", fd, fd], windowsHide: true, timeout: 600_000});
  } finally { closeSync(fd); }
  report.steps.push({script, exitCode: result.status, executionError: Boolean(result.error),
    log, sha256: sha(readFileSync(path.join(output, log)))});
  if (result.status !== 0 || result.error) break;
}
report.finishedAt = new Date().toISOString();
report.sourceUnchanged = revision === git("rev-parse", "HEAD") && !git("status", "--porcelain");
report.passed = report.sourceUnchanged && report.steps.length === 3 && report.steps.every(step => step.exitCode === 0 && !step.executionError);
writeFileSync(path.join(output, "report.json"), JSON.stringify(report, null, 2) + "\n", {flag: "wx"});
console.log(JSON.stringify(report, null, 2));
process.exitCode = report.passed ? 0 : 1;
