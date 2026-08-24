# M2 sandbox broker threat model

[한국어](../../ko/m2/broker-threat-model.md) | [M2 status](README.md)

- Status: **Draft, not approved**
- Scope: contract-foundation review only
- Recorded: 2026-08-24

This document defines the security questions that must be resolved before an OpenTCAD sandbox broker may own access to Docker or Podman. The current repository contains no broker service, product runtime adapter, socket access, or solver execution path.

## Assets and trust boundaries

Protected assets are the host, runtime socket, engine images, submitted decks, generated artifacts, job state, provenance, credentials, and other users' jobs. The future boundary is:

`browser -> loopback API -> worker -> typed broker request -> broker policy -> RuntimeBackend -> OCI runtime`

The browser, API, worker, input archive, solver deck, container output, runtime response, and stale runtime objects are untrusted. Only reviewed broker code, an approved policy profile, immutable image identities, and exact runtime capabilities may participate in an executable request.

## Threats and required controls

| Threat | Required fail-closed control | Current foundation |
|---|---|---|
| Shell or command injection | No command, shell, entrypoint, argument vector, or runtime option in a worker-controlled request | Enforced by `SandboxSpec` shape |
| Mutable or substituted image | Approved digest-pinned index and platform manifest must match inspection | Model and policy enforce identity; no real inspection yet |
| Host path or mount escape | Broker creates managed volumes; requests contain no host paths, bind mounts, devices, or runtime socket | Enforced by model shape |
| Runtime socket exposure | Only a separately reviewed broker process may receive the socket; browser, API, and worker never receive it | Architectural rule only; no broker exists |
| Capability or policy downgrade | Every required capability is positively reported; missing or unknown capability rejects the request | Enforced by policy tests |
| Archive traversal or special file | Reject absolute paths, parent traversal, links, devices, duplicate normalized names, count overflow, and size overflow before extraction | Flat manifest names are enforced; byte-stream validator is pending |
| Resource or output denial of service | Fixed CPU, memory, PID, time, output, file-count, artifact, and tmpfs ceilings | Model and policy enforce declared ceilings; runtime enforcement pending |
| Cross-job access | Server UUID labels, opaque handles, exact job ownership, managed-volume isolation, and exact artifact manifest | Mock lifecycle enforces ownership; runtime isolation pending |
| Stale state or orphan reuse | Reject existing labelled objects, use exact generated identities, cleanup container before volume, and query zero orphans | Stable stale-state errors and mock cleanup exist; crash reconciliation pending |
| State confusion and unsafe retry | Persist stable phase, error code, retry class, backend identity, terminal classification, and immutable provenance | Stable records exist; durable state machine pending |
| Diagnostic disclosure | Redact secrets and host paths; expose normalized capability and error records only | Contract avoids host paths; redaction pipeline pending |
| Backend semantic drift | Map policy separately for Docker and Podman and prove equivalent controls with contract and fault tests | Capability vocabulary exists; adapters are blocked |

## Security invariants

1. A caller cannot choose a raw executable or runtime option.
2. The policy validator is the only constructor of `ValidatedSandboxSpec`.
3. An executable profile requires all declared capabilities; there is no warning-only downgrade.
4. Image identity uses a digest-pinned reference plus exact index, platform-manifest, and platform values.
5. Inputs and outputs use single file names and exact hashes, never host paths.
6. Managed runtime objects carry exact job ownership and are removed by opaque identity.
7. GitHub Pages remains non-executing and contains no broker endpoint or credential.

## Abuse cases required before approval

- Malicious archives with `..`, absolute paths, mixed separators, Unicode normalization collisions, duplicate names, links, devices, sparse expansion, and size/count bombs.
- Forged image responses, missing capabilities, unexpected runtime versions, rootless drift, and Docker/Podman flag differences.
- Cancellation during each lifecycle phase, broker restart, runtime restart, host restart, partial cleanup, stale labels, and concurrent cleanup.
- Output flooding, artifact substitution, cross-job handle reuse, duplicate job submission, and diagnostic secret injection.
- A 20-case mixed loop and crash-recovery matrix proving zero labelled containers and volumes.

## Approval gate

Approval requires the M1 corpus to be green, the runtime ADR to be accepted, named security review, archive-validator tests, broker state-machine tests, runtime-specific policy traces, and crash-reconciliation evidence. Until then, RUN-004 and RUN-005 remain blocked and this draft authorizes no runtime access.

## Rollback

Removing `backend/app/runtime/`, the M2 manifest, and these M2 documents returns the product to its engine-free static state. The foundation creates no runtime objects, images, databases, projects, or numerical baselines.
