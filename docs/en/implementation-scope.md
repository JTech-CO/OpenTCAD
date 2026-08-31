# Implementation scope and existing-site comparison

[한국어](../ko/implementation-scope.md)

## Baseline and method

This report compares the read-only behavior reference `ypooh2042/tcad-webapp@13bce4a` with the current OpenTCAD repository. The reference README, code maps, frontend package, backend package, container definitions, and deployment layout were inspected. No upstream application source is copied into OpenTCAD.

The existing site is a functional, Linux-oriented solver application.
OpenTCAD is now a clean-room, bilingual static product plus a fail-closed local
service and OCI runtime implementation. It is not yet a feature-for-feature
solver replacement. The present release improves distribution clarity, public
accessibility, language coverage, durable lifecycle design, and cross-platform
host integration while intentionally withholding real solver execution.

## Feasible delivery models

| Model | Feasibility | Solver execution | Recommended scope |
|---|---|---:|---|
| GitHub Pages static preview | Complete now | No | Product tour, terminology, deterministic reference visuals, documentation |
| Loopback-only local server with OCI runtime | High, recommended | Yes, after license and validation gates | Primary Windows, macOS, and Linux product |
| Authenticated shared server | Medium to high after local mode | Yes | Classroom or lab deployment with accounts, quotas, audit, and backup |
| Optional desktop wrapper | Medium, optional | Through the same local server | Convenience shell around the local stack, not a second runtime architecture |
| Browser-side WASM solver | Not recommended | Theoretically partial | Poor fit for legacy SUPREM, process isolation, filesystem-heavy artifacts, and solver licensing |
| Separate native solver ports for every host OS | Low value as the primary path | Yes | Expensive and likely to diverge numerically; retain only as a future research path |

The recommended implementation keeps the established Linux solver environment inside OCI containers and absorbs host differences in launchers and runtime adapters. Docker Desktop on Windows, Docker Desktop or Podman Machine on macOS, and Docker or rootless Podman on Linux can all provide the same Linux execution contract.

## Target end-to-end implementation

```text
Browser
  -> loopback-only web gateway
  -> standard-library authenticated local API
  -> bounded execution and control worker lanes
  -> durable SQLite state, recovery, and backup control
  -> sandbox broker
  -> Docker or rootless Podman adapter
  -> isolated per-job managed volume
  -> SUPREM-IV.GS
  -> structure parser and Gmsh remeshing
  -> DEVSIM
  -> versioned artifacts, metrics, warnings, and provenance
```

The browser and API must never receive an OCI runtime socket. Only the broker may create containers, and it must accept typed allowlisted specifications rather than raw commands, paths, image names, mounts, or environment values. GitHub Pages remains a non-executing build even after local mode exists.

## Capability comparison

| Capability | Existing reference site | OpenTCAD now | Feasible OpenTCAD target |
|---|---|---|---|
| Public static access | No dedicated safe static product | Complete on GitHub Pages | Keep as the public product surface |
| English and Korean | Primarily Korean | Complete for maintained UI and product docs | Keep translation keys and paired docs in parity |
| Process deck editor | Monaco editor with real workspace files | In-memory illustrative deck | Monaco or equivalent editor with secure project storage |
| Syntax catalog and manuals | Completion, parameter tables, manual and reference panels | Not present | Clean-room catalog and licensed documentation index |
| SUPREM process execution | Real jobs through rootless Podman on Linux | Intentionally unavailable | OCI adapter after distribution and baseline approval |
| Process results | Parsed `.str`, depth profiles, 2D surfaces, stage navigation | Deterministic reference profile and cross-section | Validated parser, topology checks, metrics, and provenance |
| Device setup | Electrode mapping, sources, sweep and formulation selection | Illustrative contacts and fixed bias display | Typed device plan with validation and revisioning |
| DEVSIM analysis | Real density and quasi-Fermi workflows | Deterministic reference I–V family | Pinned images, convergence semantics, fallback evidence, golden comparison |
| Saved result comparison | Stored analyses can be overlaid and deleted | Reference curves only | Versioned result sets, comparison, export, and replay |
| Files and projects | Server filesystem workspace and file operations | No persistent projects | Portable `.tcadproj`, secure import/export, backup and migration |
| Authentication and administration | Session login, invitation flow, occupancy and admin controls | None | Omit from single-user local mode; restore for shared mode |
| Job queue and cancellation | PostgreSQL queue, worker, polling, console and cancellation | Durable typed lifecycle and cancellation contracts; UI submission disabled | Connect approved solver requests and diagnostics |
| Runtime support | Rootless Podman and server-specific Linux assumptions | Evidence-gated Docker and Podman adapters; product disabled | Qualify exact release images on three hosts |
| Packaging | Python, Node, Redis, PostgreSQL, three images, systemd and nginx | Static host plus doctor, blocked preview, and fail-closed product command | Signed and qualified platform launch packages |
| Licensing | No recognized root license and bundled solver boundary | GitHub-recognized MIT for original OpenTCAD work; solvers excluded | Component-level notices, source provenance and approved distribution profile |
| CI and deployment | Unit, integration and E2E structure; server-specific deployment | Frontend, Python contract, host-contract, punctuation, Pages, and gate checks | Add approved native runtime and numerical release matrices |

## What OpenTCAD updates

### Improvements already delivered

- A public, non-executing GitHub Pages product surface.
- An explicit MIT boundary for original OpenTCAD code and documentation.
- English and Korean UI plus paired product and engineering documentation.
- Deterministic visuals that are visibly marked as reference data rather than solver output.
- A responsive process, device, comparison, and runtime-boundary experience.
- A cross-platform target that separates domain jobs from Docker and Podman details.
- A same-origin local preview that creates no state and makes solver
  authorization visibly distinct from transport connection.
- Evidence-gated Docker and Podman adapters, native fencing, durable SQLite
  lifecycle, recovery, maintenance, authenticated archive, and scheduled
  backup integration.
- Cross-platform `doctor`, blocked `preview`, and fail-closed `serve` commands
  with strict per-user paths and operator configuration.
- Current GitHub Actions, locked JavaScript dependencies, automated tests, and a generated social preview.

### Existing functionality not yet restored

- Real SUPREM execution, `.str` parsing, Gmsh remeshing, and DEVSIM solves.
- Monaco language integration, server-backed files, tabs, manual panels, and parameter catalogs.
- Device-plan editing, saved analyses, overlays, user-facing cancellation,
  logs, and artifact downloads.
- Authentication, invitations, and administration for a future shared-server
  mode.
- Approved native runtime observations, physical power-loss runs, a
  code-owned solver release profile, platform packages, and upgrade UI.

These omissions are deliberate. Copying the existing source would undermine the clean MIT boundary, and shipping a partially isolated solver path would create a security claim that the current code cannot support.

## Current release boundary

The current public release is complete as a bilingual, non-executing product
preview. M3 also provides a runnable blocked local preview and a product host
that refuses activation before side effects. Real solver execution is not part
of this release and must not be inferred from the runtime implementation or
deterministic visuals. Activation still requires separate licensing, sandbox,
numerical, data-safety, physical power-loss, and cross-platform approval.

## Korean punctuation policy

Korean-owned prose must not use the Unicode em dash character `U+2014`. Use a colon, comma, parentheses, an ASCII hyphen, or an explicit phrase such as `not applicable`, depending on meaning. Scientific notation such as `I–V` and `Id–Vd` retains the en dash because it expresses a technical relationship. English copy may retain normal English em dash usage.
