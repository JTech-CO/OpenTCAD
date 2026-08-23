# Foundation work report

[한국어](../ko/project-foundation.md)

## Problem

The target repository contained only a 67-byte initial README, while the workspace contained the cross-platform plan, engineering harness, roadmap, backlog, and two UI references. There was no buildable application, bilingual product documentation, recognized root license, CI, or GitHub Pages artifact.

## Classification

- Priority: P0 foundation
- Risk level: L5 for licensing/distribution boundary; L1 for the static UI
- Domains: licensing, documentation, frontend, CI
- Upstream behavior reference: `ypooh2042/tcad-webapp@13bce4a`
- Target baseline: `JTech-CO/OpenTCAD@9325b01`

## Reproducer

1. Check out target baseline `9325b01`.
2. Observe that only the short README exists.
3. Attempt `npm run build`; no application or package metadata exists.
4. Inspect repository license metadata; no license is detected.

Expected: an MIT-owned, bilingual project foundation that builds as a static app and keeps third-party solver terms separate.

## Invariants at risk

- A static host must never execute submitted input.
- No browser/API component may receive a runtime socket.
- Reference-preview curves must not be represented as solver output or a numerical baseline.
- The root MIT license must not be presented as covering SUPREM-IV.GS, Gmsh, or DEVSIM.
- Existing planning content and supplied UI references must remain traceable; later punctuation-only normalization must be recorded and rehashed.

## Planned boundaries

Changed: root project metadata, paired English/Korean product documentation, frontend-only reference experience, CI and Pages workflows.

Not changed: upstream application source, SUPREM source or patches, solver version, image, runtime behavior, database, migration, numerical tolerance, or golden result.

## Tests first

The foundation adds tests for:

- an explicit static-mode execution boundary;
- English/Korean locale switching;
- a deterministic reference workflow state transition;
- paired translation key completeness;
- production-static compilation with relative asset paths.

## Validation

Verified on 2026-08-23 with Node.js 24:

- `npm run check:ko-copy`: 13 Korean documents plus UI translations passed with no `U+2014` em dash;
- `npm run lint`: passed with zero warnings;
- `npm run test`: 2 files and 9 tests passed;
- `npm run coverage`: report generated (28.24% overall; canvas drawing paths are not exercised by jsdom);
- `npm run build`: TypeScript and Vite production build passed with relative asset paths;
- `npm audit --audit-level=high`: 0 vulnerabilities;
- local static preview: `/` and `/og.png` both returned HTTP 200;
- normalized planning bundle: all 8 recorded SHA-256 hashes matched.

## Rollback

The foundation landed through PR #1 at merge commit `4a7cae9`. Reverting that merge returns the repository to the initial README and does not touch a database, runtime object, solver artifact, or user project.

## Known limitations

The current app is a reference UI, not a solver-backed release. Docker/Podman adapters, sandbox broker, FastAPI, persistence, numerical corpus, launcher, backup, project import/export, and cross-platform qualification remain roadmap work.
