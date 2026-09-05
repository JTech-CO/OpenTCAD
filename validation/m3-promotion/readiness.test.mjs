import assert from "node:assert/strict";
import {
  appendFile,
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";

import {
  M3_GATE_IDS,
  PromotionErrorCode,
  PromotionReadinessError,
  parseStrictJson,
  sha256Hex,
  validateM3Promotion,
} from "./readiness.mjs";

const REVISION = "a".repeat(40);
const APPROVAL = {
  approvalId: "11111111-1111-4111-8111-111111111111",
  approvedBy: "fixture-release-reviewer",
  approvedAt: "2026-09-01T00:00:00Z",
};
const ENTRYPOINTS = ["archive-export", "archive-import", "solver"];

async function writeJson(root, relativePath, value) {
  const path = join(root, ...relativePath.split("/"));
  await mkdir(dirname(path), { recursive: true });
  const bytes = Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf8");
  await writeFile(path, bytes);
  return sha256Hex(bytes);
}

async function readJson(root, relativePath) {
  return JSON.parse(
    await readFile(join(root, ...relativePath.split("/")), "utf8"),
  );
}

function identity(architecture, indexCharacter, manifestCharacter) {
  const indexDigest = `sha256:${indexCharacter.repeat(64)}`;
  return {
    reference: `registry.example.invalid/opentcad/solver@${indexDigest}`,
    indexDigest,
    platformManifestDigest: `sha256:${manifestCharacter.repeat(64)}`,
    platform: `linux/${architecture}`,
  };
}

function manifestIdentity(value) {
  return {
    reference: value.reference,
    index_digest: value.indexDigest,
    platform_manifest_digest: value.platformManifestDigest,
    platform: value.platform,
  };
}

async function createFixture(context) {
  const root = await mkdtemp(join(tmpdir(), "opentcad-m3-promotion-"));
  context.after(() => rm(root, { recursive: true, force: true }));
  const manifestPath = "validation/manifests/m3-entry-gates.json";
  const readinessPath = "validation/manifests/m3-promotion-readiness.json";
  const imageLockPath = "validation/manifests/m3-release-image-lock.json";

  const gateEvidence = [];
  for (const gate of M3_GATE_IDS) {
    const path = `evidence/gates/${gate}.json`;
    const sha256 = await writeJson(root, path, {
      schemaVersion: 1,
      evidenceType: "m3-promotion-fixture-gate",
      fixtureOnly: true,
      revision: REVISION,
      gate,
    });
    gateEvidence.push({ path, sha256 });
  }

  const licensePath = "evidence/release/license-review.json";
  const licenseSha256 = await writeJson(root, licensePath, {
    schemaVersion: 1,
    evidenceType: "m3-promotion-fixture-license",
    fixtureOnly: true,
    revision: REVISION,
  });
  const amd64 = identity("amd64", "1", "2");
  const arm64 = identity("arm64", "3", "4");
  const imageValues = [
    { id: "solver-amd64", identity: amd64 },
    { id: "solver-arm64", identity: arm64 },
  ];
  for (const image of imageValues) {
    const architecture = image.identity.platform.split("/")[1];
    const sbomPath = `evidence/release/sbom-${architecture}.spdx.json`;
    image.sbom = {
      path: sbomPath,
      sha256: await writeJson(root, sbomPath, {
        spdxVersion: "SPDX-2.3",
        name: `fixture-${architecture}`,
        fixtureOnly: true,
      }),
    };
    image.licenseEvidence = { path: licensePath, sha256: licenseSha256 };
    image.releaseApproved = true;
  }
  const imageLockSha256 = await writeJson(root, imageLockPath, {
    schemaVersion: 2,
    evidenceType: "m3-release-image-lock",
    revision: REVISION,
    images: imageValues,
  });

  const grants = [];
  for (const backend of ["docker", "podman"]) {
    for (const image of [amd64, arm64]) {
      for (const entrypoint of ENTRYPOINTS) {
        grants.push({
          backend,
          image: manifestIdentity(image),
          entrypoint,
        });
      }
    }
  }
  const gates = M3_GATE_IDS.map((id, index) => ({
    id,
    approved: true,
    approvedBy: `fixture-${id}-reviewer`,
    approvedAt: APPROVAL.approvedAt,
    evidence: [gateEvidence[index]],
  }));
  const manifestSha256 = await writeJson(root, manifestPath, {
    schemaVersion: 1,
    productEnabled: true,
    ...APPROVAL,
    gates,
    runtime: { grants },
  });

  const runtimeQualifications = [];
  const hostArchitectures = {
    windows: "amd64",
    macos: "arm64",
    linux: "amd64",
  };
  let evidenceSequence = 1;
  for (const platform of ["windows", "macos", "linux"]) {
    for (const backend of ["docker", "podman"]) {
      const architecture = hostArchitectures[platform];
      const releaseImage = imageValues.find(({ identity: value }) =>
        value.platform.endsWith(architecture),
      );
      const path = `evidence/runtime/${platform}-${backend}.json`;
      const sha256 = await writeJson(root, path, {
        schemaVersion: 1,
        evidenceType: "m3-native-runtime-qualification",
        evidenceId: `00000000-0000-4000-8000-${String(evidenceSequence).padStart(12, "0")}`,
        revision: REVISION,
        platform,
        backend,
        observedAt: APPROVAL.approvedAt,
        reviewer: `fixture-${platform}-${backend}-reviewer`,
        reviewedAt: APPROVAL.approvedAt,
        runtime: {
          clientVersion: `${backend}-fixture-client`,
          serverVersion: `${backend}-fixture-server`,
          serverOs: "linux",
          serverArchitecture: architecture,
          executableSha256: (backend === "docker" ? "5" : "6").repeat(64),
        },
        contractSuitePassed: true,
        nativeConformancePassed: true,
        images: [
          {
            identity: releaseImage.identity,
            sbom: releaseImage.sbom,
            entrypoints: ENTRYPOINTS,
          },
        ],
      });
      evidenceSequence += 1;
      runtimeQualifications.push({
        platform,
        backend,
        evidence: { path, sha256, revision: REVISION },
      });
    }
  }

  await writeJson(root, readinessPath, {
    schemaVersion: 1,
    evidenceType: "m3-promotion-readiness",
    revision: REVISION,
    manifest: { path: manifestPath, sha256: manifestSha256 },
    imageLock: { path: imageLockPath, sha256: imageLockSha256 },
    approval: APPROVAL,
    gates: gates.map((gate, index) => ({
      ...gate,
      evidence: [{ ...gateEvidence[index], revision: REVISION }],
    })),
    runtimeQualifications,
  });
  return { root, manifestPath, readinessPath, gateEvidence, runtimeQualifications };
}

async function rewriteJson(fixture, path, update) {
  const value = await readJson(fixture.root, path);
  update(value);
  return writeJson(fixture.root, path, value);
}

async function refreshManifestReference(fixture) {
  const manifestBytes = await readFile(
    join(fixture.root, ...fixture.manifestPath.split("/")),
  );
  await rewriteJson(fixture, fixture.readinessPath, (value) => {
    value.manifest.sha256 = sha256Hex(manifestBytes);
  });
}

async function refreshQualificationReference(fixture, path) {
  const bytes = await readFile(join(fixture.root, ...path.split("/")));
  await rewriteJson(fixture, fixture.readinessPath, (value) => {
    const qualification = value.runtimeQualifications.find(
      ({ evidence }) => evidence.path === path,
    );
    qualification.evidence.sha256 = sha256Hex(bytes);
  });
}

function validate(fixture) {
  return validateM3Promotion({
    repositoryRoot: fixture.root,
    manifestPath: fixture.manifestPath,
    readinessPath: fixture.readinessPath,
    expectedRevision: REVISION,
  });
}

function rejectsWithCode(callback, code) {
  assert.throws(callback, (error) => {
    assert.ok(error instanceof PromotionReadinessError);
    assert.equal(error.code, code);
    return true;
  });
}

test("the committed M3 state remains blocked while promotion fixtures are tested", async () => {
  const repositoryRoot = resolve(import.meta.dirname, "../..");
  const manifest = JSON.parse(
    await readFile(
      join(repositoryRoot, "validation", "manifests", "m3-entry-gates.json"),
      "utf8",
    ),
  );
  assert.equal(manifest.productEnabled, false);
  assert.equal(manifest.gates.length, 8);
  assert.ok(manifest.gates.every(({ approved }) => approved === false));
});

test("a revision-bound 8 of 8 fixture with six native rows is ready", async (context) => {
  const fixture = await createFixture(context);
  const result = validate(fixture);
  assert.deepEqual(result, {
    status: "ready",
    revision: REVISION,
    manifestSha256: (await readJson(fixture.root, fixture.readinessPath)).manifest.sha256,
    approvalId: APPROVAL.approvalId,
    approvedGateCount: 8,
    qualificationCount: 6,
    runtimeGrantCount: 12,
    imageCount: 2,
  });
});

test("one blocked gate rejects the candidate atomically", async (context) => {
  const fixture = await createFixture(context);
  await rewriteJson(fixture, fixture.manifestPath, (value) => {
    value.gates[4].approved = false;
    value.gates[4].approvedBy = null;
    value.gates[4].approvedAt = null;
  });
  await refreshManifestReference(fixture);
  rejectsWithCode(() => validate(fixture), PromotionErrorCode.PARTIAL_APPROVAL);
});

test("gate evidence byte drift fails closed", async (context) => {
  const fixture = await createFixture(context);
  await appendFile(
    join(fixture.root, ...fixture.gateEvidence[0].path.split("/")),
    "drift\n",
  );
  rejectsWithCode(() => validate(fixture), PromotionErrorCode.EVIDENCE_DRIFT);
});

test("readiness evidence cannot name another revision", async (context) => {
  const fixture = await createFixture(context);
  await rewriteJson(fixture, fixture.readinessPath, (value) => {
    value.runtimeQualifications[0].evidence.revision = "b".repeat(40);
  });
  rejectsWithCode(() => validate(fixture), PromotionErrorCode.REVISION_MISMATCH);
});

test("native qualification entrypoints must equal the exact runtime grants", async (context) => {
  const fixture = await createFixture(context);
  const path = fixture.runtimeQualifications[0].evidence.path;
  await rewriteJson(fixture, path, (value) => {
    value.images[0].entrypoints.push("unapproved-entrypoint");
  });
  await refreshQualificationReference(fixture, path);
  rejectsWithCode(
    () => validate(fixture),
    PromotionErrorCode.RUNTIME_BINDING_MISMATCH,
  );
});

test("SBOM bytes are bound through both image lock and native evidence", async (context) => {
  const fixture = await createFixture(context);
  const imageLock = await readJson(
    fixture.root,
    "validation/manifests/m3-release-image-lock.json",
  );
  await appendFile(
    join(fixture.root, ...imageLock.images[0].sbom.path.split("/")),
    "drift\n",
  );
  rejectsWithCode(() => validate(fixture), PromotionErrorCode.EVIDENCE_DRIFT);
});

test("duplicate JSON keys are rejected before approval evaluation", () => {
  rejectsWithCode(
    () => parseStrictJson('{"schemaVersion":1,"schemaVersion":1}'),
    PromotionErrorCode.INPUT_INVALID,
  );
});

test("invalid calendar timestamps are rejected", async (context) => {
  const fixture = await createFixture(context);
  await rewriteJson(fixture, fixture.readinessPath, (value) => {
    value.approval.approvedAt = "2026-02-30T00:00:00Z";
  });
  rejectsWithCode(() => validate(fixture), PromotionErrorCode.INPUT_INVALID);
});

test("runtime review cannot predate the native observation", async (context) => {
  const fixture = await createFixture(context);
  const path = fixture.runtimeQualifications[0].evidence.path;
  await rewriteJson(fixture, path, (value) => {
    value.observedAt = "2026-09-01T00:00:01Z";
    value.reviewedAt = "2026-09-01T00:00:00Z";
  });
  await refreshQualificationReference(fixture, path);
  rejectsWithCode(
    () => validate(fixture),
    PromotionErrorCode.QUALIFICATION_INCOMPLETE,
  );
});

test("manual native workflow is exact-revision and non-promoting", async () => {
  const repositoryRoot = resolve(import.meta.dirname, "../..");
  const workflow = await readFile(
    join(repositoryRoot, ".github", "workflows", "m3-native-qualification.yml"),
    "utf8",
  );
  assert.doesNotMatch(workflow, /qualify-runtime\.py/u);
  assert.match(workflow, /tools\/observe-m3-native-adapter\.py/u);
  assert.match(workflow, /environment: m3-native-qualification/u);
  assert.match(workflow, /- self-hosted/u);
  assert.match(workflow, /persist-credentials: false/u);
  assert.match(workflow, /git", "status", "--porcelain=v1"/u);
  assert.match(workflow, /\$\{\{ runner\.temp \}\}/u);
  for (const input of [
    "image_reference",
    "index_digest",
    "platform_manifest_digest",
    "image_platform",
  ]) {
    assert.match(workflow, new RegExp(`^      ${input}:`, "mu"));
  }
  assert.match(
    workflow,
    /command\.extend\(\["--wsl-distribution", "Debian"\]\)/u,
  );
  assert.match(workflow, /record\.get\("observedConformancePassed"\) is True/u);
  for (const field of [
    "qualified",
    "approvalGranted",
    "baselinePromotionAllowed",
    "releaseImageApproved",
    "solverApprovalGranted",
    "platformApprovalGranted",
    "distributionAllowed",
  ]) {
    assert.match(workflow, new RegExp(`"${field}"`, "u"));
  }
  assert.match(workflow, /record\.get\(field\) is False/u);
  assert.match(workflow, /manifest\.json/u);
  assert.match(workflow, /failure\.json/u);
});
