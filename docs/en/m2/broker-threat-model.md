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
| Archive traversal or special file | Reject absolute paths, parent traversal, links, devices, duplicate normalized names, count overflow, size overflow, and byte substitution before extraction | Canonical uncompressed input and output USTAR streams are validated in memory; product runtime transfer remains pending |
| Resource or output denial of service | Fixed CPU, memory, PID, time, output, file-count, artifact, and tmpfs ceilings | Model and policy enforce declared ceilings; runtime enforcement pending |
| Cross-job access | Server UUID labels, opaque handles, exact job ownership, managed-volume isolation, and exact artifact manifest | Mock lifecycle enforces ownership; runtime isolation pending |
| Stale state or orphan reuse | Reject existing labelled objects, use exact generated identities, serialize cleanup by job, use bounded durable leases and heartbeats, increment owner generations before cancellation or expired-owner recovery, bind runtime mutations to the exact job, owner, and token, cleanup container before volume, accept already-absent convergence, and query zero orphans | Five ownership competitions, four lease/runtime-fencing cases, concurrent guarded mock reconciliation, four recovery restart boundaries, five cancellation restart boundaries, and SQLite hard-exit takeover proof exist; native product-runtime fencing, runtime-backed reconciliation, clock-skew policy, and power-loss recovery remain pending |
| State confusion and unsafe retry | Map contiguous broker events to deterministic event and operation slots; persist owner UUID, fencing token, lease duration, and current expiry with atomic revision CAS, revision-neutral renewal, legal takeover states, terminal immutability, exact live ownership verification, and bounded recovery scans | Owner-aware complete-outcome and phase-time mapping, partial replay, ten-case conformance on memory and SQLite adapters, live-owner recovery refusal, cancellation preemption, schema-v1 and schema-v2 migration, lock redaction, restart recovery, a product-disabled coordinated offline pair snapshot, authenticated outer exports, durable maintenance coordination, restore floors, and schedule state exist; retention compaction, product broker admission and transport wiring, OS key storage, protected control-store rollback resistance, product-native fencing, bounded clock skew, and multi-host coordination remain pending |
| Snapshot substitution, rollback, or partial restore | Require maintenance admission drain, fixed files, canonical metadata, HMAC authentication, exact schemas, state-authority coherence, protected source identity, a durable minimum sequence, and fresh-directory publication | Candidate rejects torn, extra, tampered, mixed, unknown-key, identity-mismatched, below-floor, same-sequence substitution, and existing-target cases; broker auto-admission, OS key storage, protected control-store rollback resistance, and real power-loss proof remain pending |
| Diagnostic disclosure | Redact secrets and host paths; expose normalized capability and error records only | Public events omit raw detail and unrecognized backend values; raw detail exists only in repr-hidden internal diagnostics |
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
- Snapshot file substitution, duplicate JSON keys, source-instance mismatch, sequence rollback, mixed state-authority generations, interrupted publication, and restore into an existing target.
- The present 20-case mixed loop, deterministic in-memory crash boundaries, and SQLite process hard-exit proof; product runtime, host restart, power-loss, and distributed-ownership matrices must still prove zero labelled containers and volumes.

## Approval gate

Approval requires the M1 corpus to be green, the runtime ADR to be accepted, named security review, runtime-specific policy traces, durable crash-reconciliation evidence, and review of the now-present input/output archive, identity, cancellation, redaction, and mock broker state-machine tests. Until then, RUN-004 and RUN-005 remain blocked and this draft authorizes no runtime access.

## Rollback

Removing `backend/app/runtime/`, the M2 manifest, and these M2 documents returns the product to its engine-free static state. Contract tests create only isolated temporary SQLite files, snapshot bundles, and restore directories and remove them; the product creates no runtime objects, images, databases, projects, or numerical baselines.
