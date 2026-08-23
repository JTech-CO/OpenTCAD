import assert from "node:assert/strict";
import test from "node:test";

import {
  renderPinnedContainerfile,
  validateReferenceImageBuildPlan,
} from "./reference-image-build.mjs";

function plan() {
  return {
    schemaVersion: 1,
    planId: "test-build",
    baselinePromotionAllowed: false,
    distributionAllowed: false,
    reference: {
      repository: "https://example.test/reference",
      commit: "a".repeat(40),
      rawArchiveSha256: "b".repeat(64),
      commitTimestampEpoch: 1234567890,
      containerfile: {
        relativePath: "docker/suprem/Containerfile",
        sha256: "c".repeat(64),
      },
    },
    build: {
      runtime: "podman",
      format: "oci",
      pullPolicy: "never",
      noCache: true,
      cgroupManager: "cgroupfs",
      timestampEpoch: 1234567890,
      repeats: 2,
      environment: { sourceDateEpoch: "1234567890", lcAll: "C", tz: "UTC" },
      baseImages: [
        {
          stage: "builder",
          sourceLine: "FROM debian:bookworm AS builder",
          pinnedLine: `FROM debian@sha256:${"d".repeat(64)} AS builder`,
          manifestDigest: `sha256:${"d".repeat(64)}`,
          indexDigest: `sha256:${"e".repeat(64)}`,
        },
        {
          stage: "runtime",
          sourceLine: "FROM debian:bookworm-slim",
          pinnedLine: `FROM debian@sha256:${"f".repeat(64)}`,
          manifestDigest: `sha256:${"f".repeat(64)}`,
          indexDigest: `sha256:${"1".repeat(64)}`,
        },
      ],
      aptSnapshots: [
        {
          source: "http://deb.debian.org/debian",
          snapshot: "http://snapshot.debian.org/archive/debian/20260101T000000Z",
        },
        {
          source: "http://deb.debian.org/debian-security",
          snapshot: "http://snapshot.debian.org/archive/debian-security/20260101T000000Z",
        },
      ],
      checkValidUntil: false,
    },
    sbom: {
      scanner: {
        name: "syft",
        version: "1.0.0",
        reference: `example.test/syft@sha256:${"2".repeat(64)}`,
        manifestDigest: `sha256:${"2".repeat(64)}`,
        imageId: "3".repeat(64),
      },
      source: "oci-archive",
      format: "cyclonedx-json",
      network: "none",
      rawArchiveCommitted: false,
      rawSbomCommitted: false,
    },
  };
}

test("reference image build plan retains deterministic and local-only controls", () => {
  assert.equal(validateReferenceImageBuildPlan(plan()).planId, "test-build");
  assert.throws(
    () => validateReferenceImageBuildPlan({ ...plan(), distributionAllowed: true }),
    /forbid promotion and distribution/u,
  );
});

test("Containerfile rendering pins bases, snapshots, epoch, locale, and timezone", () => {
  const source = [
    "FROM debian:bookworm AS builder",
    "RUN apt-get update",
    "FROM debian:bookworm-slim",
    "USER 10001",
    "",
  ].join("\n");
  const rendered = renderPinnedContainerfile(source, plan());
  assert.match(rendered, /FROM debian@sha256:d{64} AS builder/u);
  assert.match(rendered, /ARG SOURCE_DATE_EPOCH=1234567890/u);
  assert.match(rendered, /LC_ALL=C TZ=UTC/u);
  assert.match(rendered, /snapshot\.debian\.org\/archive\/debian\/20260101T000000Z/u);
  assert.match(rendered, /Acquire::Check-Valid-Until/u);
  assert.match(rendered, /FROM debian@sha256:f{64}\n/u);
  assert.equal(rendered.includes("FROM debian:bookworm"), false);
});

test("Containerfile rendering rejects CRLF and ambiguous base lines", () => {
  const source = "FROM debian:bookworm AS builder\r\nFROM debian:bookworm-slim\r\n";
  assert.throws(() => renderPinnedContainerfile(source, plan()), /LF line endings/u);
  assert.throws(
    () =>
      renderPinnedContainerfile(
        "FROM debian:bookworm AS builder\nFROM debian:bookworm AS builder\nFROM debian:bookworm-slim\n",
        plan(),
      ),
    /must occur exactly once/u,
  );
});
