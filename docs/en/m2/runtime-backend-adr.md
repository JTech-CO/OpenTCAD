# ADR: RuntimeBackend contract boundary

[한국어](../../ko/m2/runtime-backend-adr.md) | [M2 status](README.md)

- Status: Proposed
- Decision scope: RUN-002 contract foundation
- Product adapter approval: Not granted

## Context

The reference system couples domain work to Podman-specific behavior. OpenTCAD must support Docker and rootless Podman without spreading host or runtime branches through workers. A SUPREM input can execute shell behavior, so runtime convenience cannot weaken the sandbox boundary.

M1 numerical and rights gates remain open. This ADR therefore freezes an engine-independent contract for review but does not authorize a backend that owns Docker or Podman access.

## Proposed decision

1. `RuntimeBackend` is an asynchronous Python protocol owned by the future sandbox broker.
2. Workers submit only `SandboxSpec`; they cannot submit raw runtime operations.
3. `SandboxPolicy` converts a spec to `ValidatedSandboxSpec` only after profile, image, input, output, limit, and capability checks pass.
4. Backend-specific option mapping stays inside separate Docker and Podman modules.
5. Volume and container identifiers are opaque handles. Domain code never sees host paths or engine-native IDs.
6. Every failure crossing the boundary uses a stable code, phase, retry disposition, and backend ID. Locale-dependent CLI text is diagnostic data, not control flow.
7. Missing mandatory capability is terminal for validation. Silent downgrade is forbidden.
8. Runtime image building is outside the job broker. Jobs can inspect and ensure only identities approved by an engine profile.

## Contract operations

| Area | Operations | Boundary |
|---|---|---|
| Runtime | `probe` | Normalized health, version, OS, architecture, rootless state, capabilities |
| Image | `inspect_image`, `ensure_image` | Digest-pinned `ImageIdentity` only |
| Volume | `create_volume`, `stage_inputs`, `remove_volume` | Server UUID and validated spec; no host path |
| Container | `create_container`, `start`, `wait`, `kill`, `remove_container` | Validated spec and opaque handles only |
| Artifact | `collect_artifacts` | Expected names, hashes, counts, and byte limits |
| Repair | `list_managed` | Label-scoped managed objects for exact cleanup |

## Mandatory execution capabilities

Image inspect and digest verification, managed volumes, validated input and artifact transfer, container lifecycle, bounded output, CPU/memory/PID/time limits, network none, all capabilities dropped, no-new-privileges, read-only root, writable tmpfs control, fixed non-root user, labels, and orphan query are mandatory.

Image pull is reported separately. A missing pull capability does not weaken an execution if an approved image is already present; an image that cannot be inspected and matched is rejected.

## Cross-runtime mapping

Equivalent policy does not imply identical flags. The M0 OCI observation showed that Podman needs explicit read-only tmpfs control to match the reviewed temporary-filesystem behavior. Future adapters must report that capability and implement their own mapping. Domain workers may not branch on Docker, Podman, Windows, WSL, or Podman Machine.

## Detection and override

Runtime auto-detection is deferred to RUN-006. The eventual decision must use deterministic precedence, an explicit administrator override, normalized doctor output, and a stable unavailable error. The contract foundation does not inspect the host or select a runtime.

## Consequences

- The broker can be tested with a strict in-memory backend before any socket is introduced.
- Product adapters will share lifecycle and error tests but retain separate argument or API mapping.
- New capability fields require contract and policy review.
- Canonical input/output archive validation, fixed job identity, phase-addressable cancellation, process-local cleanup serialization, public/internal diagnostic separation, deterministic outcome and mock-only phase-time mapping, the common adapter conformance suite, the durable-state interface, an inactive SQLite candidate, startup recovery admission, partial-write cleanup, and separate-process hard-exit recovery are implemented in the broker foundation; product runtime transfer, external cancellation persistence, distributed fencing, backup, and power-loss qualification remain separate gated responsibilities.
- This proposal cannot be marked accepted until the required review and M2 entry evidence exist.

## Rollback

Deleting `backend/app/runtime/` and the M2 manifest returns the repository to the engine-free product state. Tests create and remove isolated temporary SQLite files; no product database, user project, runtime object, image, or baseline is created by this foundation.
