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
| LIC-003 third-party and image inventory | In progress | Docker and Podman image identities plus one external Docker SBOM were observed; Podman SBOM, license conclusions, and reproducible builds remain open |
| LIC-004 release image policy | Not started | Must reject unapproved or unpinned images |
| BASE-001 Linux reference baseline | In progress, not met | Rootless Podman met the declared profile and matched Docker structure bytes; log, image-rebuild, SBOM, rights, and review gates still fail |
| Current architecture record | Draft complete | Target and reference boundaries are recorded |
| Portability spikes | Preflight observed | Windows Docker Desktop and WSL2 rootless Podman produced diagnostic evidence but no support claim |
| M0 exit gate | Not met | Numerical, platform, and support-matrix evidence remains open |

## M0 artifacts

- [License strategy](license-strategy.md)
- [Baseline and clean-room policy](baseline-and-clean-room.md)
- [BASE-001 reference observation harness](base001-reference-observation.md)
- [Current architecture](current-architecture.md)
- [Portability spike report](portability-spike-report.md)
- [Machine-readable dependency and image inventory](../../../m0/DEPENDENCY_AND_IMAGE_INVENTORY.json)
- [Machine-readable baseline freeze](../../../m0/BASELINE_FREEZE.json)
- [Machine-readable ineligible Docker observation](../../../m0/BASE001_DOCKER_OBSERVATION.json)
- [Machine-readable ineligible rootless Podman observation](../../../m0/BASE001_ROOTLESS_PODMAN_OBSERVATION.json)
- [Five-run 1D observation plan](../../../validation/plans/base001-process-1d-boron.json)

`npm run check:m0` validates both observation records, collector hashes, immutable-commit formatting, image approval rules, English/Korean document pairs, and fail-closed status. Rootless Podman met the declared environment profile and reproduced the Docker structure exactly, but declared solver log errors, image drift, the missing Podman-image SBOM, rights, and numerical review keep BASE-001 open.

## Next gates

1. Obtain a qualified decision for SUPREM source, patch, binary, and image distribution.
2. Correct the declared input errors, make the Podman image reproducible, and generate a local image SBOM.
3. Run the proposed NMOS process/device and CMOS process/device cases.
4. Freeze reviewed input, output, log, metric, image, and repeated-run evidence.
5. Run native Linux, Windows, macOS, and Podman Machine portability spikes against that same baseline.

Engine-independent M1 contract work may proceed in `gated-active` mode. No numerical corpus may be frozen and no solver-backed product claim may begin until the applicable M0 gates are met.
