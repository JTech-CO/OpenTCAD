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
| LIC-003 third-party and image inventory | In progress | Critical inventory is frozen; image digests and SBOMs remain open |
| LIC-004 release image policy | Not started | Must reject unapproved or unpinned images |
| BASE-001 Linux reference baseline | Pending | Requires an authorized solver environment and immutable images |
| Current architecture record | Draft complete | Target and reference boundaries are recorded |
| Portability spikes | Pending | Begin only after the reference baseline can be reproduced |
| M0 exit gate | Not met | Numerical, platform, and support-matrix evidence remains open |

## M0 artifacts

- [License strategy](license-strategy.md)
- [Baseline and clean-room policy](baseline-and-clean-room.md)
- [Current architecture](current-architecture.md)
- [Portability spike report](portability-spike-report.md)
- [Machine-readable dependency and image inventory](../../../m0/DEPENDENCY_AND_IMAGE_INVENTORY.json)
- [Machine-readable baseline freeze](../../../m0/BASELINE_FREEZE.json)

`npm run check:m0` validates the records, local evidence hashes, immutable-commit formatting, image approval rules, and English/Korean document pairs.

## Next gates

1. Obtain a qualified decision for SUPREM source, patch, binary, and image distribution.
2. Reproduce the frozen reference on Linux x86-64 with rootless Podman and capture immutable image digests.
3. Run the proposed 1D process, NMOS process/device, and CMOS process/device cases.
4. Freeze input, output, log, metric, and image hashes plus repeated-run variance.
5. Run Windows, macOS, and Podman Machine portability spikes against that same baseline.

Engine-independent M1 contract work may proceed in `gated-active` mode. No numerical corpus may be frozen and no solver-backed product claim may begin until the applicable M0 gates are met.
