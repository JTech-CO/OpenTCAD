# M0 license strategy

[한국어](../../ko/m0/license-strategy.md) | [M0 status](README.md)

## Decision in force

OpenTCAD-owned code and new documentation are released under MIT. The current public artifact is the engine-free static build. It must not contain SUPREM-IV.GS, reference-application patches, DEVSIM, Gmsh, solver images, or an installer that fetches or silently installs those artifacts.

The solver distribution decision is blocked, not approved. A blocked decision is an explicit M0 outcome and prevents an accidental mixed-license release.

## Evidence

- The OpenTCAD repository has a root `LICENSE` and `NOTICE`.
- The frozen reference application has no root license that authorizes copying its application code.
- `SUPREM4GS/upstream/LICENSE` at the frozen reference commit is a Stanford 1994 custom notice. It is not MIT and contains a commercial-transaction restriction.
- The reference provenance points to `rafael1193/suprem4gs` commit `33e90433a9d1e5134deaa8773f59be37d3256b13` and applies separate patches. Patch ownership and distribution permission are not yet established for OpenTCAD.
- The official DEVSIM repository identifies Apache-2.0 and includes a NOTICE.
- The official Gmsh documentation identifies GPL version 2 or later with the Gmsh exception.
- The reference image tags are mutable and contain transitive operating-system packages. A tag name is not sufficient license or reproducibility evidence.

Hashes and exact selectors are stored in [`m0/DEPENDENCY_AND_IMAGE_INVENTORY.json`](../../../m0/DEPENDENCY_AND_IMAGE_INVENTORY.json).

## Candidate distribution models

| Model | Current status | Approval condition |
|---|---|---|
| A. Mixed-license source and prebuilt images | Blocked | Qualified review of every component, patch, notice, source-offer duty, and image SBOM |
| B. Optional engine supplied or built by the user | Preferred interim direction, not approved | Confirm that OpenTCAD scripts and instructions do not redistribute restricted artifacts and fail closed when engines are absent |
| C. Permission-based bundle | Pending | Written permission covering the intended source, binary, image, installer, and commercial contexts |
| Engine-free static release | Approved | Keep the automated no-solver boundary and third-party notices current |

Model B is the engineering preference because it preserves the MIT application boundary, but preference is not legal clearance.

## Release rules

1. Keep OpenTCAD-owned code, integration adapters, and documentation under the root MIT license.
2. Keep third-party license texts, notices, provenance, patches, and source-offer material adjacent to the artifact that requires them.
3. Pin every release image by digest. Generate an SBOM and package-license report from the exact built image.
4. Treat an unknown license, mutable image, missing NOTICE, or missing source provenance as a release failure.
5. Do not use a runtime download as a way to bypass a distribution restriction.
6. Do not imply that the MIT license relicenses a solver, upstream example, screenshot, manual, or patch.
7. Require a maintainer and qualified reviewer to record the final model before any solver-backed public release.

## Open decisions

- Whether the SUPREM notice permits the intended noncommercial and commercial OpenTCAD distribution paths.
- Who owns the reference patches and under what terms OpenTCAD may reproduce or replace their behavior.
- Whether DEVSIM 2.10.1 wheels contain additional notices or bundled libraries.
- The exact Debian, Python, Gmsh, OpenBLAS, Redis, and PostgreSQL artifacts and licenses in each release image.
- Whether the installer remains engine-free, builds locally from user-provided source, or ships an approved bundle.
