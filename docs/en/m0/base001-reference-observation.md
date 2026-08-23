# BASE-001 reference observation harness

[한국어](../../ko/m0/base001-reference-observation.md) | [M0 status](README.md)

## Outcome

OpenTCAD now has a fail-closed, engine-independent observation harness for external reference runs. It verifies a frozen Git commit and exact input blob, probes the OCI runtime and image identity, executes without a shell, stores raw evidence outside the repository, hashes every input, log, and artifact, measures exact repeatability, and never changes a baseline or image lock.

The first five-run observation is useful evidence but **does not complete BASE-001**. It ran on Docker Desktop rather than rootless Podman, the image did not reproduce byte-for-byte in a no-cache rebuild, and every solver invocation emitted declared command-input errors despite returning exit code 0.

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
2. Reproduce the same plan on Linux amd64 rootless Podman;
3. make the image build byte-reproducible and review immutable manifests and SBOM license conclusions;
4. replace or correct the failing plot commands using an authorized, independently reviewed fixture;
5. add NMOS and CMOS process-device observations plus fault-path tests;
6. promote evidence only through explicit maintainer and semiconductor numerical review.
