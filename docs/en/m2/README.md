# M2 runtime contract foundation

[한국어](../../ko/m2/README.md)

M2 is `gated-active`. The runtime-neutral model, stable errors, fail-closed policy validator, protocol, canonical input/output-archive validators, fixed job identity, phase-addressable cancellation, redacted public events, process-local cleanup coordinator, deterministic broker-event mapping, reusable state-adapter conformance suite, reusable native-object runtime-fence conformance suite, durable-state interface, inactive file-backed SQLite candidate, crash/restart recovery coordinator, inactive mock-only phase-time composition, strict mock backend, and internal mock broker orchestrator are implemented for contract review. The explicit inactive composition live-wires both execution and external cancellation to the candidate for mock-only tests. External cancellation commits intent before runtime query, uses revision CAS for one winner, and preserves that decision across restart. Fresh internal owner attempts and monotonically increasing fencing tokens now arbitrate execution, cancellation, and recovery at checked store and broker boundaries. A shared process-local fence authority now activates and verifies every bound mock operation, while managed mock objects persist and enforce exact fencing labels. The composition is not product-enabled. No Docker or Podman product adapter, sandbox broker service transport, runtime detection, worker integration, runtime socket access, or solver execution exists.

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
| RUN-007 contract suite | Inactive native-object fencing conformance tested | 121 tests include archive attacks, two 20-case loops, eleven execution cancellation checkpoints, concurrent cleanup, phase-time execution and cancellation persistence, ten-case memory and SQLite adapter conformance, startup admission, partial-write handling, four recovery crash boundaries, five cancellation crash boundaries, five ownership competition cases, schema-v1 and schema-v2 migration, four owner-lease cases, five common runtime-fence adapter cases, three focused authority and post-mutation cases, a separate-process hard exit, reconciliation, redaction, and durable-state semantics |
| BRK-001 typed broker protocol | Foundation tested | Internal library accepts typed spec plus canonical bytes and returns redacted records |
| BRK-003 managed volume lifecycle | Mock tested | Create, stage, run, collect, container removal, volume removal, and zero-object query |
| BRK-004 archive defense | Input/output foundation tested | Canonical bytes, traversal, links, devices, compression, metadata, collisions, bombs, substitution, and drift fail closed |
| BRK-006 recovery and reconciliation | Candidate fenced recovery tested | Startup drains recoverable pages before admission; each recovery uses a fresh owner generation; newer recovery fences stale reconciliation; committed cancellation intent closes as cancelled and unacknowledged running state closes as failed |
| BRK-007 cancellation identity | Durable fenced mock cancellation tested | Every job kind shares one UUID identity, all eleven execution checkpoints clean to zero objects, and external cancellation takes over with the next token before runtime contact |
| BRK-008 structured events/redaction | Durable owner-state mapping tested | Deterministic execution and cancellation mapping persists normalized owner UUIDs and fencing tokens, retains cancelled classification through cleaning, and omits raw detail |
| M2 exit | Not met | Durable lease liveness, shared mock authority, native-object label persistence, and reusable runtime-fence conformance are tested, but broker service, solver corpus, product runtime adapters with native token enforcement, cross-process authority, power-loss proof, and native platform qualification are absent |

## Implemented boundary

The future worker can construct only a `SandboxSpec` containing a server UUID, approved profile ID, job kind, immutable image identity, fixed input manifest, bounded limits, approved environment profile, and expected output names. The model has no field for a command, shell, entrypoint, host path, mount, network mode, user, capability, security option, device, or runtime socket.

Only `SandboxPolicy.validate()` can create `ValidatedSandboxSpec`. A backend receives that validated type, opaque volume and container handles, and stable termination reasons. Unsupported mandatory capabilities are reported as `capability-missing`; the policy never drops an option and continues.

The mock backend invokes no process and owns no socket. The internal broker library validates exact uncompressed input and output USTAR streams in memory, accepts only `ValidatedInputArchive` at staging, creates `ValidatedArtifactArchive` only after byte and manifest agreement, and uses a fixed `JobIdentity` for execution and external cancellation. Execution polls eleven typed cancellation checkpoints. Cleanup, cancellation, and reconciliation share a process-local job coordinator, remove containers before volumes, treat already-absent observed handles as convergence, and re-query managed objects before reporting cleanup success. The durable composition rejects missing, terminal, cancelling, and cleaning cancellation admissions before runtime contact and lets only the committed CAS winner proceed.

`DurableJobStateStore` fixes atomic revision CAS, event UUID and operation-slot idempotency, legal transitions, terminal immutability, redacted persisted fields, bounded recovery scanning, and exact ownership verification. Every event carries a logical operation UUID, fresh owner-attempt UUID, and monotonically increasing fencing token. `BrokerStateMapper` and `StateEventRecorder` define deterministic complete-outcome mapping and partial replay. The ten-case common conformance suite runs against both the non-durable memory double and `SQLiteJobStateStore`. Every committed event carries a bounded lease duration; renewal extends the mutable current-lease row without changing the job revision or append-only event history. The SQLite candidate uses schema v3, WAL, `synchronous=FULL`, and `BEGIN IMMEDIATE`; it migrates exact schema v1 files through v2 and exact schema v2 files to v3 transactionally, fails closed on unknown schemas, and performs no automatic retention. `CrashRecoveryCoordinator` verifies four deterministic recovery boundaries, while a separate Python process proves that a committed SQLite claim survives `os._exit` and is fenced by a fresh recovery owner after reopen before convergence. `LiveStateSession` and `DurableBrokerComposition` await phase writes, drain startup recovery before admission, continue fail-safe cleanup after ordinary write failure, and leave incomplete prefixes recoverable. Execution begins at token 1; cancellation and expired-owner recovery takeovers increment the token before runtime work, while recovery reports `owner-active` for a live lease. Ownership guards renew before, during, and after guarded awaits, cancel the Python awaitable if ownership is lost, and prevent an expired or stale owner from appending or writing a terminal state. Every job lifecycle call is made through a RuntimeFencingContext; a shared process-local authority activates immediately before and verifies immediately after each bound operation. Managed mock volumes and containers persist the exact three fencing labels and revalidate them on every operation. Normal lifecycle work requires an exact object generation, while a higher takeover generation may only query, kill, or clean predecessor objects. The strict mock runtime rejects lower tokens, same-token owner ambiguity, malformed labels, cross-job contexts, and mismatched handles. A post-operation authority check suppresses stale success after an in-flight mock mutation, and the current owner converges cleanup to zero objects. Stale public outcomes use `operation-fenced`. Direct broker execution and cancellation retain their prior non-persisted behavior. Service transport, product activation, product Docker or Podman token persistence and enforcement, native in-flight revocation, backup and restore, multi-host coordination, and power-loss qualification remain absent.

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
- [Durable operation ownership and fencing](durable-operation-ownership.md)
- [Owner lease, liveness, and runtime fencing](owner-lease-runtime-fencing.md)
- [Native-object runtime fencing conformance](native-runtime-fence-conformance.md)
- [`RuntimeBackend` protocol](../../../backend/app/runtime/protocol.py)
- [Runtime fence authority](../../../backend/app/runtime/fence_authority.py)
- [Runtime fencing labels and object rules](../../../backend/app/runtime/fencing.py)
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
- [Durable operation ownership tests](../../../backend/tests/broker/test_operation_ownership.py)
- [Owner lease and runtime fencing tests](../../../backend/tests/broker/test_owner_lease_runtime_fencing.py)
- [Runtime fence common conformance suite](../../../backend/tests/runtime/fence_conformance.py)
- [Runtime fence authority and concrete mock tests](../../../backend/tests/runtime/test_runtime_fence_conformance.py)

Run the foundation with:

```sh
npm run check:m2
npm run test:runtime
```

Python 3.12 through 3.14 is supported for this dependency-free contract suite. CI pins Python 3.12.

## Next gate

Review and approve the ADR and threat model only after the unresolved M1 entry evidence is addressed. A future product Docker or Podman adapter must implement the established authority, label persistence, inspection, object-generation rules, and pre-operation and post-operation checks, then pass the five common adapter cases unchanged and produce native-platform evidence for in-flight revocation or safe convergence. Cross-process durable authority, atomic store-to-runtime activation, backup and restore, power-loss qualification, multi-host coordination, clock-skew policy, and product activation remain later gates. Real Docker and Podman adapters remain blocked until an approved immutable engine profile and the applicable M2 entry gates exist.
