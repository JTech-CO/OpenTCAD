# M0 current architecture record

[한국어](../../ko/m0/current-architecture.md) | [M0 status](README.md)

## OpenTCAD target at M0 start

OpenTCAD currently consists of a bilingual React and Vite static application, deterministic reference preview data, documentation, and GitHub Pages deployment. It has no backend, database, queue, worker, container runtime adapter, solver source, solver binary, or solver image.

The static application is a useful product shell, not a simulation service. Its browser-only boundary is deliberate while licensing and numerical baselines remain open.

## Frozen behavior reference

The read-only reference at commit `13bce4a9daba5796ceee633fb8cd0c870465f766` describes a different operational system:

```text
Browser
  -> React frontend
  -> FastAPI backend
  -> PostgreSQL and Redis
  -> worker and job state
  -> per-job rootless Podman sandbox
       -> SUPREM-IV.GS process image
       -> Gmsh remesh image
       -> DEVSIM device image
  -> logs, structures, curves, and artifacts
```

This diagram records externally relevant components and trust boundaries. It is not permission to copy the reference implementation.

## Target architecture direction

```text
GitHub Pages
  -> engine-free static preview and documentation

Loopback-only local service
  -> bilingual web UI
  -> API and durable job state
  -> runtime-neutral sandbox broker
       -> Docker adapter
       -> Podman adapter
  -> separately governed engine packages
       -> process
       -> remesh
       -> device
```

The runtime contract must use immutable engine identities, managed job storage, no network by default, read-only roots, non-root users, dropped capabilities, explicit CPU/memory/PID/time/output limits, and structured failure semantics.

## Gaps recorded in M0

- No OpenTCAD local API, worker, job state, runtime adapter, or installer exists yet.
- The reference uses mutable base and service image tags.
- WSL2 rootless Podman met the declared profile for one 1D case, but no authorized OpenTCAD baseline is approved.
- Docker Desktop and WSL2 Podman preflights are measured; native Linux, Podman Machine, macOS, and full fault behavior remain open.
- Solver distribution and patch rights are not approved.
- No scientific result can be compared until immutable inputs, engines, metrics, and tolerances are frozen.

These gaps keep M0 open and define the evidence needed before the runtime implementation begins.
