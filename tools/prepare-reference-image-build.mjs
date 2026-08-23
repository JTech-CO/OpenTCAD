import { createHash } from "node:crypto";
import { mkdir, readFile, realpath, writeFile } from "node:fs/promises";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { pathIsWithin, sha256Hex } from "../validation/baseline/observation.mjs";
import {
  renderPinnedContainerfile,
  validateReferenceImageBuildPlan,
} from "../validation/baseline/reference-image-build.mjs";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const toolPath = fileURLToPath(import.meta.url);
const libraryPath = fileURLToPath(
  new URL("../validation/baseline/reference-image-build.mjs", import.meta.url),
);

function usage() {
  return [
    "Usage:",
    "  node tools/prepare-reference-image-build.mjs --plan <repository-plan>",
    "    --source-root <external-raw-tree> --output-containerfile <external-file>",
    "    --metadata-output <external-json>",
    "",
    "The source root, generated Containerfile, and metadata must remain outside OpenTCAD.",
    "The frozen source tree is never modified.",
  ].join("\n");
}

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") return { help: true };
    if (!argument.startsWith("--")) throw new Error(`Unexpected argument: ${argument}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for ${argument}.`);
    const name = argument.slice(2);
    if (options[name] !== undefined) throw new Error(`Duplicate option: ${argument}.`);
    options[name] = value;
    index += 1;
  }
  return options;
}

function requireOption(options, name) {
  const value = options[name];
  if (typeof value !== "string" || value.length === 0) throw new Error(`--${name} is required.`);
  return value;
}

function requireExternal(path, label) {
  if (pathIsWithin(projectRoot, path)) throw new Error(`${label} must be outside OpenTCAD.`);
}

async function fileIdentity(path, repositoryPath) {
  const bytes = await readFile(path);
  return { path: repositoryPath, sha256: createHash("sha256").update(bytes).digest("hex") };
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  if (options.help) {
    console.log(usage());
    return;
  }

  const planPath = resolve(projectRoot, requireOption(options, "plan"));
  if (!pathIsWithin(projectRoot, planPath)) throw new Error("--plan must stay inside OpenTCAD.");
  const sourceRoot = await realpath(resolve(requireOption(options, "source-root")));
  requireExternal(sourceRoot, "--source-root");
  const outputContainerfile = resolve(requireOption(options, "output-containerfile"));
  const metadataOutput = resolve(requireOption(options, "metadata-output"));
  requireExternal(outputContainerfile, "--output-containerfile");
  requireExternal(metadataOutput, "--metadata-output");
  if (pathIsWithin(sourceRoot, outputContainerfile) || pathIsWithin(sourceRoot, metadataOutput)) {
    throw new Error("Generated evidence must not modify the frozen source tree.");
  }
  if (outputContainerfile === metadataOutput) throw new Error("Output files must be distinct.");

  const planBytes = await readFile(planPath);
  const plan = validateReferenceImageBuildPlan(JSON.parse(planBytes.toString("utf8")));
  const sourceContainerfile = resolve(sourceRoot, plan.reference.containerfile.relativePath);
  if (!pathIsWithin(sourceRoot, sourceContainerfile)) {
    throw new Error("The planned Containerfile escapes the frozen source root.");
  }
  const sourceBytes = await readFile(sourceContainerfile);
  const sourceSha256 = sha256Hex(sourceBytes);
  if (sourceSha256 !== plan.reference.containerfile.sha256) {
    throw new Error(
      `Frozen Containerfile hash mismatch: expected ${plan.reference.containerfile.sha256}, got ${sourceSha256}.`,
    );
  }

  const rendered = renderPinnedContainerfile(sourceBytes.toString("utf8"), plan);
  await mkdir(dirname(outputContainerfile), { recursive: true });
  await mkdir(dirname(metadataOutput), { recursive: true });
  await writeFile(outputContainerfile, rendered, { encoding: "utf8", flag: "wx" });

  const generatedSha256 = sha256Hex(Buffer.from(rendered));
  const collectorFiles = await Promise.all([
    fileIdentity(toolPath, "tools/prepare-reference-image-build.mjs"),
    fileIdentity(libraryPath, "validation/baseline/reference-image-build.mjs"),
    Promise.resolve({
      path: plan.reference.containerfile.planPath ?? "validation/plans/base001-suprem-image-build.json",
      sha256: sha256Hex(planBytes),
    }),
  ]);
  const metadata = {
    schemaVersion: 1,
    recordedAt: new Date().toISOString(),
    planId: plan.planId,
    reference: {
      commit: plan.reference.commit,
      rawArchiveSha256: plan.reference.rawArchiveSha256,
      sourceContainerfile: {
        relativePath: plan.reference.containerfile.relativePath,
        sha256: sourceSha256,
      },
    },
    generatedContainerfile: {
      filename: basename(outputContainerfile),
      sha256: generatedSha256,
      sourceTreeModified: false,
    },
    controls: {
      timestampEpoch: plan.build.timestampEpoch,
      environment: plan.build.environment,
      baseImageManifestDigests: plan.build.baseImages.map(({ stage, manifestDigest }) => ({
        stage,
        manifestDigest,
      })),
      aptSnapshots: plan.build.aptSnapshots.map(({ snapshot }) => snapshot),
    },
    collectorFiles,
  };
  await writeFile(metadataOutput, `${JSON.stringify(metadata, null, 2)}\n`, {
    encoding: "utf8",
    flag: "wx",
  });
  console.log(JSON.stringify(metadata));
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  console.error(usage());
  process.exitCode = 1;
});
