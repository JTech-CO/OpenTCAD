# M2 runtime contract foundation

[한국어](../../ko/m2/README.md)

M2 is `gated-active`. The runtime-neutral model, stable errors, fail-closed policy validator, protocol, canonical input/output-archive validators, fixed job identity, phase-addressable cancellation, redacted public events, process-local cleanup coordinator, deterministic broker-event mapping, reusable state-adapter conformance suite, durable-state interface, mock crash/restart recovery coordinator, strict mock backend, and internal mock broker orchestrator are implemented for contract review. No durable database, Docker or Podman product adapter, sandbox broker service transport, runtime detection, worker integration, or runtime socket access exists.

M2 entry is not met because the M1 corpus is not green, the runtime ADR is proposed rather than approved, and the broker threat model is a draft rather than approved.

## Workboard

| Item | Status | Current evidence |
|---|---|---|
| RUN-001 runtime characterization | Observed, non-promoting | Docker Desktop and WSL2 rootless Podman passed the non-solver OCI fault matrix |
| RUN-002 `RuntimeBackend` contract | Foundation tested | Typed async lifecycle, capability model, stable errors, and strict mock backend |
| RUN-003 common sandbox policy | Foundation tested | Missing capabilities, mutable image identity, profile drift, and excessive limits fail closed |
| RUN-004 Podman adapter | Blocked | Entry gates and approved engine profile are missing |
| RUN-005 Docker adapter | Blocked | Entry gates and approved engine profile are missing |
| RUN-006 runtime detection | Not started | Deterministic precedence and explicit override remain an ADR follow-up |
| RUN-007 contract suite | Mock recovery contract tested | Sixty-seven tests include archive attacks, two 20-case loops, eleven cancellation checkpoints, concurrent cleanup, event mapping, adapter conformance, four crash boundaries, reconciliation, redaction, and durable-state semantics |
| BRK-001 typed broker protocol | Foundation tested | Internal library accepts typed spec plus canonical bytes and returns redacted records |
| BRK-003 managed volume lifecycle | Mock tested | Create, stage, run, collect, container removal, volume removal, and zero-object query |
| BRK-004 archive defense | Input/output foundation tested | Canonical bytes, traversal, links, devices, compression, metadata, collisions, bombs, substitution, and drift fail closed |
| BRK-006 recovery and reconciliation | Mock crash/restart contract tested | Shared job leases serialize cleanup; common adapter tests verify CAS and reopen semantics; four crash boundaries converge through exact-job reconciliation |
| BRK-007 cancellation identity | Phase matrix tested | Every job kind shares one UUID identity, and all eleven execution checkpoints cancel with exact zero-object cleanup |
| BRK-008 structured events/redaction | Mapping and redaction tested | Deterministic outcome mapping persists only normalized fields; public and persisted shapes omit raw detail |
| M2 exit | Not met | No real adapter, broker service, solver corpus, durable store, external-process crash proof, or native platform qualification |

## Implemented boundary

The future worker can construct only a `SandboxSpec` containing a server UUID, approved profile ID, job kind, immutable image identity, fixed input manifest, bounded limits, approved environment profile, and expected output names. The model has no field for a command, shell, entrypoint, host path, mount, network mode, user, capability, security option, device, or runtime socket.

Only `SandboxPolicy.validate()` can create `ValidatedSandboxSpec`. A backend receives that validated type, opaque volume and container handles, and stable termination reasons. Unsupported mandatory capabilities are reported as `capability-missing`; the policy never drops an option and continues.

The mock backend invokes no process and owns no socket. The internal broker library validates exact uncompressed input and output USTAR streams in memory, accepts only `ValidatedInputArchive` at staging, creates `ValidatedArtifactArchive` only after byte and manifest agreement, and uses a fixed `JobIdentity` for execution and external cancellation. Execution polls eleven typed cancellation checkpoints. Cleanup, cancellation, and reconciliation share a process-local job coordinator, remove containers before volumes, treat already-absent observed handles as convergence, and re-query managed objects before reporting cleanup success.

`DurableJobStateStore` now fixes atomic revision CAS, event UUID and operation-slot idempotency, legal transitions, terminal immutability, redacted persisted fields, and bounded recovery scanning. `BrokerStateMapper` and `StateEventRecorder` define deterministic complete-outcome mapping and partial replay. A common conformance suite verifies fresh-handle visibility, conflicts, CAS, and pagination. `CrashRecoveryCoordinator` verifies four mock crash boundaries and fail-safe restart convergence. `InMemoryJobStateStore` and its shared fixture backing are not durable. The running broker is not wired to this interface, and no service transport, database adapter, migration, distributed lease, or external-process durability proof exists.

## Artifacts

- [RuntimeBackend ADR](runtime-backend-adr.md)
- [Sandbox broker threat model](broker-threat-model.md)
- [Broker and canonical archive foundation](broker-archive-foundation.md)
- [Output, cancellation, and redaction foundation](output-cancellation-redaction.md)
- [Lifecycle cancellation, cleanup, and state contract](lifecycle-cleanup-state.md)
- [Event mapping, adapter conformance, and restart recovery](event-state-recovery.md)
- [`RuntimeBackend` protocol](../../../backend/app/runtime/protocol.py)
- [Runtime models](../../../backend/app/runtime/models.py)
- [Fail-closed policy](../../../backend/app/runtime/policy.py)
- [Stable errors](../../../backend/app/runtime/errors.py)
- [Mock backend](../../../backend/app/runtime/mock_backend.py)
- [Canonical archive validator](../../../backend/app/broker/archive.py)
- [Mock broker orchestrator](../../../backend/app/broker/orchestrator.py)
- [Lifecycle cancellation contract](../../../backend/app/broker/lifecycle.py)
- [Cleanup coordinator](../../../backend/app/broker/cleanup.py)
- [Durable-state interface](../../../backend/app/broker/state.py)
- [Broker event-state mapper](../../../backend/app/broker/state_mapping.py)
- [Crash/restart recovery coordinator](../../../backend/app/broker/recovery.py)
- [Runtime contract tests](../../../backend/tests/runtime/test_mock_backend.py)
- [Archive defense tests](../../../backend/tests/broker/test_archive.py)
- [Broker cleanup tests](../../../backend/tests/broker/test_orchestrator.py)
- [Cancellation and redaction tests](../../../backend/tests/broker/test_cancellation_redaction.py)
- [Phase cancellation tests](../../../backend/tests/broker/test_lifecycle_control.py)
- [Concurrent cleanup tests](../../../backend/tests/broker/test_cleanup_concurrency.py)
- [Durable-state interface tests](../../../backend/tests/broker/test_state_store.py)
- [State-adapter conformance tests](../../../backend/tests/broker/test_state_store_conformance.py)
- [Event mapping tests](../../../backend/tests/broker/test_state_mapping.py)
- [Crash/restart recovery tests](../../../backend/tests/broker/test_recovery.py)

Run the foundation with:

```sh
npm run check:m2
npm run test:runtime
```

Python 3.12 through 3.14 is supported for this dependency-free contract suite. CI pins Python 3.12.

## Next gate

Review and approve the ADR and threat model only after the unresolved M1 entry evidence is addressed. The next state slice should select and review a real durable adapter, prove transaction and separate-process restart behavior, define migration and retention policy, and then wire phase-time broker events to storage without widening runtime authority. Real Docker and Podman adapters remain blocked until an approved immutable engine profile and the applicable M2 entry gates exist.
