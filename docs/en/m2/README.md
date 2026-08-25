# M2 runtime contract foundation

[한국어](../../ko/m2/README.md)

M2 is `gated-active`. The runtime-neutral model, stable errors, fail-closed policy validator, protocol, canonical input/output-archive validators, fixed job identity, phase-addressable cancellation, redacted public events, process-local cleanup coordinator, deterministic broker-event mapping, reusable state-adapter conformance suite, durable-state interface, inactive file-backed SQLite candidate, crash/restart recovery coordinator, inactive mock-only phase-time composition, strict mock backend, and internal mock broker orchestrator are implemented for contract review. The explicit inactive composition live-wires both execution and external cancellation to the candidate for mock-only tests. External cancellation commits intent before runtime query, uses revision CAS for one winner, and preserves that decision across restart. The composition is not product-enabled. No Docker or Podman product adapter, sandbox broker service transport, runtime detection, worker integration, runtime socket access, or solver execution exists.

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
| RUN-007 contract suite | Inactive durable cancellation contract tested | Ninety-four tests include archive attacks, two 20-case loops, eleven execution cancellation checkpoints, concurrent cleanup, phase-time execution and cancellation persistence, memory and SQLite adapter conformance, startup admission, partial-write handling, four recovery crash boundaries, five cancellation crash boundaries, a separate-process hard exit, reconciliation, redaction, and durable-state semantics |
| BRK-001 typed broker protocol | Foundation tested | Internal library accepts typed spec plus canonical bytes and returns redacted records |
| BRK-003 managed volume lifecycle | Mock tested | Create, stage, run, collect, container removal, volume removal, and zero-object query |
| BRK-004 archive defense | Input/output foundation tested | Canonical bytes, traversal, links, devices, compression, metadata, collisions, bombs, substitution, and drift fail closed |
| BRK-006 recovery and reconciliation | Candidate restart-safe cancellation gate tested | Startup drains recoverable pages before admission; common adapter tests verify memory and SQLite CAS; committed cancellation intent survives interruption and exact-job reconciliation closes it as cancelled; unacknowledged running state closes as failed |
| BRK-007 cancellation identity | Durable mock cancellation tested | Every job kind shares one UUID identity, all eleven execution checkpoints clean to zero objects, and external cancellation commits intent before runtime contact |
| BRK-008 structured events/redaction | Durable cancellation mapping tested | Deterministic execution and cancellation mapping persists normalized fields, retains cancelled classification through cleaning, and omits raw detail |
| M2 exit | Not met | Mock-only execution and external cancellation wiring are tested, but broker service, solver corpus, product runtime adapters, power-loss proof, durable ownership fencing, and native platform qualification are absent |

## Implemented boundary

The future worker can construct only a `SandboxSpec` containing a server UUID, approved profile ID, job kind, immutable image identity, fixed input manifest, bounded limits, approved environment profile, and expected output names. The model has no field for a command, shell, entrypoint, host path, mount, network mode, user, capability, security option, device, or runtime socket.

Only `SandboxPolicy.validate()` can create `ValidatedSandboxSpec`. A backend receives that validated type, opaque volume and container handles, and stable termination reasons. Unsupported mandatory capabilities are reported as `capability-missing`; the policy never drops an option and continues.

The mock backend invokes no process and owns no socket. The internal broker library validates exact uncompressed input and output USTAR streams in memory, accepts only `ValidatedInputArchive` at staging, creates `ValidatedArtifactArchive` only after byte and manifest agreement, and uses a fixed `JobIdentity` for execution and external cancellation. Execution polls eleven typed cancellation checkpoints. Cleanup, cancellation, and reconciliation share a process-local job coordinator, remove containers before volumes, treat already-absent observed handles as convergence, and re-query managed objects before reporting cleanup success. The durable composition rejects missing, terminal, cancelling, and cleaning cancellation admissions before runtime contact and lets only the committed CAS winner proceed.

`DurableJobStateStore` fixes atomic revision CAS, event UUID and operation-slot idempotency, legal transitions, terminal immutability, redacted persisted fields, and bounded recovery scanning. `BrokerStateMapper` and `StateEventRecorder` define deterministic complete-outcome mapping and partial replay. The unchanged common conformance suite runs against both the non-durable memory double and `SQLiteJobStateStore`. The SQLite candidate uses an append-only schema v1, WAL, `synchronous=FULL`, and `BEGIN IMMEDIATE`; it fails closed on unknown schema versions and performs no automatic retention. `CrashRecoveryCoordinator` verifies four deterministic recovery boundaries, while a separate Python process proves that a committed SQLite claim survives `os._exit` and converges after reopen. `LiveStateSession` and `DurableBrokerComposition` provide an explicit mock-only path that awaits phase writes, drains startup recovery before admission, continues cleanup after a write failure, and leaves incomplete prefixes recoverable. Durable external cancellation adds five deterministic interruption seams and commits `cancelling/query` before runtime query. A later write failure produces public `failed`, never a false durable success, while restart closes committed cancellation intent as `cancelled`. Direct broker execution and cancellation retain their prior non-persisted behavior. Service transport, product activation, durable ownership fencing, backup and restore, and power-loss qualification remain absent.

## Artifacts

- [RuntimeBackend ADR](runtime-backend-adr.md)
- [Sandbox broker threat model](broker-threat-model.md)
- [Broker and canonical archive foundation](broker-archive-foundation.md)
- [Output, cancellation, and redaction foundation](output-cancellation-redaction.md)
- [Lifecycle cancellation, cleanup, and state contract](lifecycle-cleanup-state.md)
- [Event mapping, adapter conformance, and restart recovery](event-state-recovery.md)
- [SQLite durable-state candidate](sqlite-durable-state.md)
- [Inactive live-state composition](live-state-composition.md)
- [Durable external cancellation arbitration](durable-cancellation-arbitration.md)
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
- [SQLite durable-state candidate](../../../backend/app/broker/sqlite_state.py)
- [Broker event-state mapper](../../../backend/app/broker/state_mapping.py)
- [Crash/restart recovery coordinator](../../../backend/app/broker/recovery.py)
- [Phase-time state session](../../../backend/app/broker/live_state.py)
- [Inactive durable broker composition](../../../backend/app/broker/state_composition.py)
- [Durable cancellation crash seams](../../../backend/app/broker/cancellation_arbitration.py)
- [Runtime contract tests](../../../backend/tests/runtime/test_mock_backend.py)
- [Archive defense tests](../../../backend/tests/broker/test_archive.py)
- [Broker cleanup tests](../../../backend/tests/broker/test_orchestrator.py)
- [Cancellation and redaction tests](../../../backend/tests/broker/test_cancellation_redaction.py)
- [Phase cancellation tests](../../../backend/tests/broker/test_lifecycle_control.py)
- [Concurrent cleanup tests](../../../backend/tests/broker/test_cleanup_concurrency.py)
- [Durable-state interface tests](../../../backend/tests/broker/test_state_store.py)
- [State-adapter conformance tests](../../../backend/tests/broker/test_state_store_conformance.py)
- [SQLite conformance and hard-exit tests](../../../backend/tests/broker/test_sqlite_state_store.py)
- [Event mapping tests](../../../backend/tests/broker/test_state_mapping.py)
- [Crash/restart recovery tests](../../../backend/tests/broker/test_recovery.py)
- [Live-state composition tests](../../../backend/tests/broker/test_state_composition.py)
- [Durable cancellation arbitration tests](../../../backend/tests/broker/test_durable_cancellation.py)

Run the foundation with:

```sh
npm run check:m2
npm run test:runtime
```

Python 3.12 through 3.14 is supported for this dependency-free contract suite. CI pins Python 3.12.

## Next gate

Review and approve the ADR and threat model only after the unresolved M1 entry evidence is addressed. The next state slice is durable operation ownership and fencing across execution, cancellation, and recovery without widening runtime authority. Backup and restore, power-loss qualification, multi-host coordination, and product activation remain later gates. Real Docker and Podman adapters remain blocked until an approved immutable engine profile and the applicable M2 entry gates exist.
