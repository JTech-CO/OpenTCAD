# M0 discovery and baseline status

[한국어](../../ko/m0/README.md)

M0 is active. This record starts the licensing, provenance, architecture, and baseline work without claiming that a solver-backed local release is ready.

## Current release boundary

| Surface | Status | Reason |
|---|---|---|
| OpenTCAD-owned MIT source and bilingual documentation | Approved | Covered by the repository MIT license |
| Engine-free GitHub Pages preview | Approved | Contains no solver source, binary, or image |
| Local server shell without bundled engines | Design allowed | Runtime contract and launcher are not implemented yet |
| SUPREM-IV.GS source, patches, binary, or image | Blocked | The custom notice and patch rights require qualified review |
| DEVSIM, Gmsh, or all-in-one solver images | Review required | Exact artifacts, notices, digests, and transitive licenses are not frozen |

This is an engineering distribution gate, not legal advice.

## Workboard

| Work item | Status | Evidence or next gate |
|---|---|---|
| LIC-001 OpenTCAD root license | Complete | `LICENSE`, `NOTICE`, and GitHub license recognition |
| LIC-002 SUPREM distribution decision | Blocked | Qualified review or written permission is required |
| LIC-003 third-party and image inventory | In progress | A controlled Podman image now rebuilds exactly and has an external local-only SBOM; license conclusions and release approval remain open |
| LIC-004 release image policy | Not started | Must reject unapproved or unpinned images |
| BASE-001 Linux reference baseline | In progress, not met | Rootless Podman matched Docker structure bytes and a controlled image rebuild is exact; clean-log, rights, SBOM review, corpus, and approval gates remain open |
| Current architecture record | Draft complete | Target and reference boundaries are recorded |
| Portability spikes | Preflight observed | Windows Docker Desktop and WSL2 rootless Podman produced diagnostic evidence but no support claim |
| Engine-independent fault paths | Contract tested, runtime evidence pending | Timeout, cancellation, combined output cap, and worker reset use real child processes but no OCI runtime or solver |
| M0 exit gate | Not met | Numerical, platform, runtime-fault, and support-matrix evidence remains open |

## M0 artifacts

- [License strategy](license-strategy.md)
- [Baseline and clean-room policy](baseline-and-clean-room.md)
- [BASE-001 reference observation harness](base001-reference-observation.md)
- [Engine-independent fault-path contract](fault-path-foundation.md)
- [Machine-readable fault-path status](../../../validation/manifests/m0-fault-path-foundation.json)
- [Current architecture](current-architecture.md)
- [Portability spike report](portability-spike-report.md)
- [Machine-readable dependency and image inventory](../../../m0/DEPENDENCY_AND_IMAGE_INVENTORY.json)
- [Machine-readable baseline freeze](../../../m0/BASELINE_FREEZE.json)
- [Machine-readable ineligible Docker observation](../../../m0/BASE001_DOCKER_OBSERVATION.json)
- [Machine-readable ineligible rootless Podman observation](../../../m0/BASE001_ROOTLESS_PODMAN_OBSERVATION.json)
- [Machine-readable controlled image and SBOM observation](../../../m0/BASE001_REPRODUCIBLE_IMAGE_OBSERVATION.json)
- [Five-run 1D observation plan](../../../validation/plans/base001-process-1d-boron.json)
- [Controlled reference image build plan](../../../validation/plans/base001-suprem-image-build.json)
- [External build preparation tool](../../../tools/prepare-reference-image-build.mjs)

`npm run check:m0` validates the two run observations, controlled image observation, build plan, collector hashes, image and SBOM identities, the engine-independent fault-path contract, English/Korean document pairs, and fail-closed status. The timestamp-, base-, and snapshot-pinned Podman image rebuilt to the same ID, digest, size, and five layers, and a network-disabled local scan produced a CycloneDX SBOM. A real child-process suite now proves timeout, cancellation, combined-output capping, and post-fault worker replacement at the contract layer. Actual OCI adapter cleanup and solver fault evidence remain pending. Declared solver log errors, rights, SBOM license review, corpus coverage, and numerical approval keep BASE-001 open.

## Next gates

1. Obtain a qualified decision for SUPREM source, patch, binary, and image distribution.
2. Review the external SBOM license evidence and approve or reject a release image recipe.
3. Correct the declared input errors using an authorized, independently reviewed fixture.
4. Run the proposed NMOS process/device and CMOS process/device cases, then repeat timeout, cancellation, output-limit, and restart through real runtime adapters.
5. Freeze reviewed evidence, then run native Linux, Windows, macOS, and Podman Machine portability spikes against it.

Engine-independent M1 contract work may proceed in `gated-active` mode. No numerical corpus may be frozen and no solver-backed product claim may begin until the applicable M0 gates are met.
