# BASE-001 reference observation harness

[한국어](../../ko/m0/base001-reference-observation.md) | [M0 status](README.md)

## Outcome

OpenTCAD now has a fail-closed, engine-independent observation harness for external reference runs. It verifies a frozen Git commit and exact input blob, probes the OCI runtime and image identity, executes without a shell, stores raw evidence outside the repository, hashes every input, log, and artifact, measures exact repeatability, and never changes a baseline or image lock.

Two five-run observations and one controlled image-build follow-up now provide useful evidence but **do not complete BASE-001**. The Docker Desktop run missed the required runtime and rootless profile. A later WSL2 Debian run met the declared Linux amd64 rootless Podman profile and reproduced the same structure bytes and topology counts. The original image rebuilds drifted and every solver invocation emitted declared command-input errors despite returning exit code 0. A separate digest-, snapshot-, and timestamp-pinned build later reproduced exactly and produced a local-only SBOM, but it is not an authorized baseline or release image.

## Implemented controls

- [`observe-reference-run.mjs`](../../../tools/observe-reference-run.mjs) rejects output paths inside OpenTCAD and accepts only argument arrays, not shell command strings.
- The source tree may be separate from the Git checkout, but each input file must hash to the frozen Git blob. This supports raw LF build contexts without weakening provenance.
- The checked-in [1D boron plan](../../../validation/plans/base001-process-1d-boron.json) requires five runs, a read-only container root, no network, no capabilities, `no-new-privileges`, PID, memory, CPU, and timeout limits.
- Declared stderr or stdout failure markers override exit code 0. A required artifact must exist in every run and retain one exact hash before repeatability is reported.
- The generated manifest is always an observation. `baselinePromotionAllowed` is hard-coded to `false`; a conforming run can reach only `review-required`, never automatic approval.

## 2026-08-24 Docker Desktop observation

The sanitized machine record is [`m0/BASE001_DOCKER_OBSERVATION.json`](../../../m0/BASE001_DOCKER_OBSERVATION.json). Raw solver logs, structures, plots, runtime probes, and the SBOM remain outside the MIT repository.

| Evidence | Observation |
|---|---|
| Frozen reference | `ypooh2042/tcad-webapp@13bce4a9daba5796ceee633fb8cd0c870465f766` |
| Required profile | Linux amd64, rootless Podman |
| Observed profile | Docker 29.6.2 on Docker Desktop 4.84.0, Linux amd64, not rootless |
| Image | `opentcad-reference/suprem@sha256:325fdd0f81712519764ceb78baf728afea899357728cc5e05a5bebc5c30bf865`, local only |
| Input | Frozen Git blob `c28fd878ccb9ac2cc687b0a882ec4a51d91a05d9`, SHA-256 `fab7228f...9684` |
| Required output | 5,784-byte `boron.str`, SHA-256 `971dfc50...b45b` in all five runs |
| Topology records | 43 nodes, 42 elements, 2 regions, 0 boundary records in all five runs |
| Reference comparison | Generated structure matches frozen fixture Git blob `ec08539c5a4e5070d04c197249c4b5956a1632df` |
| Exit and logs | Exit code 0 in all runs, but two unknown-parameter findings and one command-input-error finding per run |
| Optional plot | Not produced |
| No-cache rebuild | Digest `sha256:f8c5ee27...a0126`; config matched, layers and final digest did not |
| SBOM | SPDX 2.3, 130 packages, SHA-256 `5635a9af...27a2`; every concluded license is `NOASSERTION` |
| Baseline result | `ineligible`; BASE-001 remains pending |

This is why OpenTCAD does not equate process exit with numerical success. The repeated structure is a useful behavioral observation, but it is not an approved golden result.

## 2026-08-24 WSL2 rootless Podman observation

The second sanitized machine record is [`m0/BASE001_ROOTLESS_PODMAN_OBSERVATION.json`](../../../m0/BASE001_ROOTLESS_PODMAN_OBSERVATION.json). Raw logs, structures, runtime probes, images, and build output remain outside OpenTCAD.

| Evidence | Observation |
|---|---|
| Host | WSL2, Debian 13 trixie, kernel `6.18.33.2-microsoft-standard-WSL2` |
| Runtime profile | Podman 5.4.2, Linux amd64, rootless, cgroup v2 with cgroupfs fallback |
| Profile evaluation | All four declared checks passed: runtime, OS, architecture, and rootless |
| First image | ID `bbfe2ae2...b1318`, digest `sha256:225eff7d...60b3b`, local only |
| No-cache rebuild | ID `37fc29a1...07d3`, digest `sha256:ad9afbb0...1407`; config and four non-base layers differed |
| Solver binary | SHA-256 `9c6d7a0b...b7805` in both Podman builds |
| Required output | The same 5,784-byte structure SHA-256 `971dfc50...b45b` in all five runs and in the Docker observation |
| Logs | The same two unknown-parameter findings and one command-input-error finding in every run |
| Podman-image SBOM | Not generated during this run; a later controlled build generated a separate local-only SBOM |
| Baseline result | `ineligible`; the runtime profile gate was observed, but BASE-001 remains pending |

Podman initially needed the Debian `passt` package for its selected `pasta` rootless network command. Noninteractive `wsl.exe` sessions did not expose a systemd user bus, so image builds selected cgroupfs explicitly and observation runs used Podman's reported cgroupfs fallback. These are setup findings, not host-support claims.

## Controlled reproducible image and local SBOM follow-up

The sanitized record is [`m0/BASE001_REPRODUCIBLE_IMAGE_OBSERVATION.json`](../../../m0/BASE001_REPRODUCIBLE_IMAGE_OBSERVATION.json), backed by the [reviewed build plan](../../../validation/plans/base001-suprem-image-build.json). The preparer verified the frozen external Containerfile hash, left the source tree unchanged, and generated the pinned recipe only outside OpenTCAD.

| Evidence | Observation |
|---|---|
| Deterministic controls | Two amd64 base manifests, Debian 2026-08-03 snapshots, commit epoch `1787471368`, `SOURCE_DATE_EPOCH`, locale `C`, UTC, OCI format, `--pull=never`, and `--no-cache` |
| Two builds | Same image ID `b5007db9...ed735`, manifest digest `sha256:49320295...e1095`, size, created timestamp, and all five rootfs layers |
| Solver binary | SHA-256 `9c6d7a0b...b7805`, identical to the earlier rootless observation |
| Local scan | Syft 1.51.0 pinned by amd64 manifest digest, rootless, read-only, all capabilities dropped, no new privileges, and network disabled |
| CycloneDX | Version 1.7, 3,077 components: 88 packages, 2,988 files, and one operating system; all 88 packages have PURLs and license evidence |
| Archive link | The exported OCI manifest uses digest `sha256:d55a7174...d897` and points to config `sha256:b5007db9...ed735`, matching the reproducible image ID |
| Review result | Technical reproducibility and local SBOM generation observed; distribution, license conclusions, baseline promotion, and support remain unapproved |

The first scan attempt allocated only 64 MiB of temporary storage and failed closed while its update check was blocked by `--network none`. The empty output was discarded. The successful scan disabled update checks explicitly, used a 512 MiB temporary filesystem, and kept the OCI archive and CycloneDX document outside the repository.

## Windows checkout finding

The first image build from the ordinary Windows checkout failed because `core.autocrlf=true` converted source and patch files to CRLF, so patch hunks no longer matched. A separate `git archive` created with `core.autocrlf=false` and `core.eol=lf` was extracted outside OpenTCAD. Four build-critical files were checked against their frozen Git blob IDs before the successful local build. No reference source, patch, binary, image, or raw solver artifact was added to this repository.

## Running an observation

Build the local reference image only after confirming that local use is allowed in the intended environment. Then run:

```text
npm run observe:base001 -- \
  --plan validation/plans/base001-process-1d-boron.json \
  --reference-workspace <external-frozen-git-clone> \
  --source-root <external-raw-byte-source-tree> \
  --output <new-directory-outside-opentcad> \
  --runtime podman
```

The command exits nonzero when a process fails, a required artifact is absent, a timeout occurs, or a declared log failure is found. Environment-profile mismatches are recorded as `ineligible`; they do not silently rewrite the required profile.

## Remaining gates

1. Obtain qualified review of SUPREM and reference-patch rights.
2. Review the SBOM license evidence and approve or reject an authorized release image recipe.
3. Replace or correct the failing plot commands using an authorized, independently reviewed fixture.
4. Add NMOS and CMOS process-device observations plus fault-path tests.
5. Promote evidence only through explicit maintainer and semiconductor numerical review.
