# OpenTCAD architecture

[한국어](../ko/architecture.md)

## Product modes

OpenTCAD deliberately separates a safe static experience from the future solver-backed local product.

| Mode | Where it runs | Can execute a deck? | Purpose |
|---|---|---:|---|
| Static preview | GitHub Pages or any static host | No | Explore the workflow, UI, terminology, and deterministic reference visuals |
| Local | Loopback-only local web server plus OCI runtime | Yes, after sandbox validation | Single-user process and device simulation |
| Shared/server | Managed host with authentication and quotas | Yes, after sandbox validation | Classroom, lab, or maintained server use |

The static build contains no runtime credentials, engine socket, subprocess bridge, uploaded code execution, or hidden solver endpoint. Editing the deck in static mode changes browser memory only.

## Target local flow

```text
Browser
  │ same-origin HTTP
  ▼
Web gateway ──► FastAPI ──► PostgreSQL / Redis
                    │ queues typed jobs
                    ▼
                  Worker
                    │ SandboxSpec only
                    ▼
             Sandbox broker
                    │ validated OCI operations
                    ▼
        Docker or rootless Podman adapter
                    │
          per-job managed volume
             ├─ SUPREM-IV.GS
             ├─ Gmsh remeshing
             └─ DEVSIM analysis
```

The API does not execute simulators. The worker does not construct raw runtime commands. Only the sandbox broker can reach the runtime, and it accepts a typed, allowlisted request rather than arbitrary image, command, environment, or mount values.

## Non-negotiable sandbox policy

Every real solver job must fail closed unless the runtime can enforce all of the following:

- no network;
- all Linux capabilities dropped;
- no-new-privileges;
- read-only root filesystem;
- fixed non-root UID/GID;
- exactly one isolated writable job volume;
- CPU, memory, PID, time, file-count, and output limits;
- no host namespace, device, runtime socket, or arbitrary bind mount;
- digest-pinned image and fixed entrypoint allowlists.

A SUPREM input deck is treated as arbitrary shell-capable input, not as a harmless domain-specific language. The browser never passes user content into an argv, image name, host path, environment key, or entrypoint.

## Static reference-data contract

The current UI uses deterministic, code-owned reference-preview values so the complete product shape can be reviewed before solver distribution is approved. Reference visuals are always labelled **not solver output**. They are not numerical baselines, cannot be exported as validated results, and must never be presented as converged data.

When a local engine is connected later, every result will carry provenance: app revision, runtime backend and architecture, image digests, engine versions, input hashes, convergence warnings, fallback decisions, and skipped points.

## Repository direction

```text
frontend/                 Static-compatible React application
docs/en/ and docs/ko/     Paired product and engineering documentation
.github/workflows/        CI and GitHub Pages deployment

backend/app/runtime/      Runtime protocol, policy, detection, adapters (planned)
backend/app/broker/       Allowlist, lifecycle, cleanup, diagnostics (planned)
packaging/compose/        Local/shared/server profiles (planned)
packaging/launcher/       PowerShell and POSIX launcher (planned)
validation/               Golden corpus and comparators (planned)
```

The current foundation intentionally does not add placeholder runtime code that could be mistaken for a secure implementation. Runtime work begins only after license and numerical-baseline gates are satisfied.
