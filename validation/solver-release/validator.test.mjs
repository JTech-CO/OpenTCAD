import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  parseStrictJson,
  runSolverReleaseCli,
  validateSolverReleaseDocument,
  validateSolverReleaseFile,
} from "../../tools/check-m3-solver-release.mjs";

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const FIXTURE_PATH = "validation/solver-release/fixtures/valid-contract.json";
const DUPLICATE_KEY_PATH = path.join(
  ROOT,
  "validation",
  "solver-release",
  "fixtures",
  "invalid-duplicate-key.json",
);
const REQUIRED_ROLES = ["transfer", "suprem", "devsim", "gmsh"];
const REQUIRED_PLATFORMS = ["linux/amd64", "linux/arm64"];

function fixture() {
  return JSON.parse(readFileSync(path.join(ROOT, ...FIXTURE_PATH.split("/")), "utf8"));
}

function validateContract(candidate) {
  return validateSolverReleaseDocument(candidate, {
    root: ROOT,
    allowContractFixture: true,
  });
}

function allArtifacts(value, found = []) {
  if (Array.isArray(value)) {
    for (const item of value) allArtifacts(item, found);
  } else if (value && typeof value === "object") {
    if (
      typeof value.path === "string" &&
      typeof value.sha256 === "string" &&
      Number.isInteger(value.bytes)
    ) {
      found.push(value);
    }
    for (const child of Object.values(value)) allArtifacts(child, found);
  }
  return found;
}

test("contract fixture validates only through the explicit test-only API option", () => {
  const result = validateSolverReleaseFile(FIXTURE_PATH, {
    root: ROOT,
    allowContractFixture: true,
  });
  assert.deepEqual(result, {
    releaseId: "m3-contract-fixture-v1",
    productVersion: "0.0.0-contract",
    evidenceClass: "contract-fixture",
    artifactCount: 44,
  });
  assert.throws(
    () => validateSolverReleaseFile(FIXTURE_PATH, { root: ROOT }),
    /contract-fixture evidence is never accepted for a product release/,
  );
});

test("production CLI rejects contract fixtures", () => {
  const errors = [];
  const exitCode = runSolverReleaseCli(
    [
      "--candidate",
      FIXTURE_PATH,
      "--root",
      ROOT,
    ],
    {
      log: () => assert.fail("contract fixture must not reach the CLI success path"),
      error: (message) => errors.push(message),
    },
  );
  assert.equal(exitCode, 1);
  assert.equal(errors.length, 1);
  assert.match(
    errors[0],
    /M3 solver release evidence rejected: contract-fixture evidence is never accepted for a product release/,
  );
});

test("fixture artifacts stay inside the fixture tree and cannot be relabeled as product evidence", () => {
  const candidate = fixture();
  const artifacts = allArtifacts(candidate);
  assert.equal(artifacts.length, 44);
  for (const artifact of artifacts) {
    assert.match(artifact.path, /^validation\/solver-release\/fixtures\/artifacts\//);
  }

  candidate.evidenceClass = "release-evidence";
  candidate.releaseId = "m3-release-candidate-1";
  candidate.productVersion = "1.0.0";
  candidate.rights.supremIvGs.source.repository = "https://github.com/JTech-CO/OpenTCAD";
  assert.throws(
    () => validateContract(candidate),
    /points to contract-fixture data, which is never product release evidence/,
  );
});

test("strict JSON parser rejects duplicate keys before validation", () => {
  assert.throws(
    () => parseStrictJson(readFileSync(DUPLICATE_KEY_PATH, "utf8"), "duplicate-key fixture"),
    /duplicate key "schemaVersion"/,
  );
});

test("source commits accept exactly 40 or 64 lowercase hexadecimal characters", () => {
  const validCommits = [
    "0123456789abcdef0123456789abcdef01234567",
    "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  ];
  for (const commit of validCommits) {
    const candidate = fixture();
    candidate.rights.supremIvGs.source.commit = commit;
    assert.doesNotThrow(() => validateContract(candidate), `expected ${commit.length}-hex commit to pass`);
  }

  for (const length of [39, 41, 63, 65]) {
    const candidate = fixture();
    candidate.rights.supremIvGs.source.commit = `0123456789abcdef${"a".repeat(length - 16)}`;
    assert.throws(
      () => validateContract(candidate),
      /rights\.supremIvGs\.source\.commit has an invalid format/,
      `expected ${length}-hex commit to fail`,
    );
  }
});

test("every image role requires the exact unique amd64 and arm64 platform set", () => {
  const valid = fixture();
  assert.deepEqual(valid.images.map((image) => image.role), REQUIRED_ROLES);
  for (const image of valid.images) {
    assert.deepEqual(image.platforms.map((platform) => platform.platform), REQUIRED_PLATFORMS);
  }

  for (const role of REQUIRED_ROLES) {
    const missing = fixture();
    missing.images.find((image) => image.role === role).platforms.pop();
    assert.throws(
      () => validateContract(missing),
      new RegExp(`images\\[\\d+\\]\\.platforms must contain exactly linux/amd64 and linux/arm64`),
      `${role} must reject a missing arm64 platform`,
    );

    const duplicate = fixture();
    duplicate.images.find((image) => image.role === role).platforms[1].platform = "linux/amd64";
    assert.throws(
      () => validateContract(duplicate),
      new RegExp(`images\\[\\d+\\]\\.platforms\\[1\\]\\.platform is duplicated`),
      `${role} must reject a duplicate platform`,
    );
  }
});

test("artifact hash drift is rejected", () => {
  const candidate = fixture();
  candidate.images[0].recipe.sha256 =
    "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef";
  assert.throws(
    () => validateContract(candidate),
    /images\[0\]\.recipe\.sha256 does not match the artifact bytes/,
  );
});

test("mutable image references are rejected", () => {
  const candidate = fixture();
  candidate.images[0].reference = candidate.images[0].reference.replace(
    "@sha256:",
    ":latest@sha256:",
  );
  assert.throws(
    () => validateContract(candidate),
    /images\[0\]\.reference must be an immutable repository reference without a mutable tag/,
  );
});

test("partial redistribution rights are rejected", () => {
  const candidate = fixture();
  candidate.rights.supremPatches.redistribution.approved = false;
  assert.throws(
    () => validateContract(candidate),
    /rights\.supremPatches\.redistribution\.approved must be true/,
  );
});

test("SBOM subject must equal and internally bind the platform manifest digest", () => {
  const candidate = fixture();
  candidate.images[0].platforms[0].sbom.subjectDigest =
    candidate.images[0].platforms[1].manifestDigest;
  assert.throws(
    () => validateContract(candidate),
    /images\[0\]\.platforms\[0\]\.sbom\.subjectDigest must equal the platform manifest digest/,
  );
});

test("corpus tolerance and repeat contracts fail closed", () => {
  const badTolerance = fixture();
  badTolerance.numericalCorpus.cases[0].tolerances[0].absolute = -0.001;
  assert.throws(
    () => validateContract(badTolerance),
    /tolerances\[0\]\.absolute must be a finite non-negative number/,
  );

  const tooFewDeclaredRepeats = fixture();
  tooFewDeclaredRepeats.numericalCorpus.cases[0].repeats = 4;
  assert.throws(
    () => validateContract(tooFewDeclaredRepeats),
    /repeats must be an integer greater than or equal to 5/,
  );

  const insufficientObservedRepeats = fixture();
  insufficientObservedRepeats.numericalCorpus.cases[0].repeats = 6;
  assert.throws(
    () => validateContract(insufficientObservedRepeats),
    /results\.repeats must satisfy the declared repeat count/,
  );
});

test("corpus provenance must bind the release image and platform manifest", () => {
  const candidate = fixture();
  candidate.numericalCorpus.cases[0].provenance = {
    path: "validation/solver-release/fixtures/artifacts/corpus/invalid-suprem-provenance.json",
    sha256: "ca6587d2d44a0cf5fe984a6bd708c5020195f4ae45d541166b0f5f1e396801c8",
    bytes: 571,
  };
  assert.throws(
    () => validateContract(candidate),
    /provenance platform manifest is not in the release image index/,
  );
});

test("unapproved reviewers are rejected at rights, corpus, and release boundaries", () => {
  for (const mutate of [
    (candidate) => {
      candidate.rights.devsim.obligationsReview.approved = false;
    },
    (candidate) => {
      candidate.numericalCorpus.cases[0].review.approved = false;
    },
    (candidate) => {
      candidate.releaseReview.approved = false;
    },
  ]) {
    const candidate = fixture();
    mutate(candidate);
    assert.throws(() => validateContract(candidate), /approved must be true/);
  }
});
