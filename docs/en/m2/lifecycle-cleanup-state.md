# M2 lifecycle cancellation, cleanup, and state contract

[한국어](../../ko/m2/lifecycle-cleanup-state.md) | [M2 status](README.md)

- Status: `gated-active`, mock only
- Work items: BRK-006 and BRK-007 contract extension
- Product runtime and product state-store activation: not granted

This contract defines deterministic cancellation and recovery seams around the internal mock broker. It adds no HTTP or IPC service, solver, product runtime adapter, host extraction, or runtime socket access. The companion inactive SQLite candidate uses a standard-library database and a test-only child process without granting product authority.

## Lifecycle cancellation checkpoints

`SandboxBroker.execute()` accepts an in-process `CancellationSignal` and polls it at eleven fixed checkpoints. `PhaseCancellation` is the deterministic contract-test implementation.

| Checkpoint | Stable runtime phase | Owned objects when reached | Cancellation action |
|---|---|---|---|
| `probe` | `probe` | None | Stop before runtime probing |
| `policy` | `validate` | None | Stop before policy validation |
| `input-archive` | `input` | None | Stop before canonical input validation |
| `image` | `image` | None | Stop before image verification |
| `volume` | `volume` | None | Stop before volume allocation |
| `input-stage` | `input` | Volume | Remove the volume |
| `container-create` | `create` | Volume | Remove the volume |
| `start` | `start` | Container and volume | Remove the unstarted container, then the volume |
| `wait` | `wait` | Running container and volume | Kill with `TerminationReason.CANCELLATION`, then clean |
| `artifact-collection` | `artifact` | Terminal container and volume | Discard the runtime result and outputs, then clean without a second kill |
| `cleanup` | `cleanup` | Terminal container and volume | Discard the result at the final pre-cleanup fence, then run cleanup to completion |

The signal identity must exactly equal the request `JobIdentity`, and its decision must be a boolean. Cancellation remains observable until the broker's terminal outcome is committed. Cleanup is shielded from cancellation: a request at the `cleanup` checkpoint changes the intended terminal state but never skips object removal or the zero-object verification. This injection seam is not a cancellation transport and does not provide cross-process arbitration.

## Concurrent cleanup idempotence

`JobCleanupCoordinator` grants one process-local lease per canonical job UUID. Execution cleanup, typed cancellation, and reconciliation use the same injectable coordinator, so multiple broker instances in one process can share the serialization boundary.

Every cleanup attempt follows these rules:

1. acquire the exact job lease;
2. inspect or act only on handles owned by that job;
3. remove the container before the volume;
4. treat `container-not-found` and `volume-not-found` after an observed handle as convergence to the desired absent state;
5. re-query the exact job and report success only when zero managed objects remain;
6. release and forget the lease after the last waiter exits.

Concurrent reconcile calls therefore return complete reports even when only the first call removes objects. A concurrent typed cancellation and reconcile also converge to zero objects. This is an in-process idempotence contract. A durable distributed lease, ownership epoch, and cross-process cancellation arbitration remain unimplemented.

## Durable state interface

`DurableJobStateStore` defines three async operations shared by the memory double and the SQLite candidate:

- `load(identity)` reads the latest immutable snapshot;
- `append(event, expected_revision=...)` atomically compares the current revision and appends one redacted event;
- `scan_recoverable(after=..., limit=...)` provides a bounded, ordered startup-recovery scan.

`DurableJobEvent` contains only job UUID, event UUID, operation UUID and positive operation sequence, broker state, runtime phase, stable error code and retry disposition, normalized backend, terminal classification, and cleanup completion. It has no raw detail, archive payload, command, secret, host path, runtime-native ID, or database message.

Revisions start at one and increase by one. The event UUID is an idempotency key, and each `(job_id, operation_id, operation_sequence)` slot is unique. Replaying an identical event returns its original snapshot; reusing either identity with different content fails with `event-conflict`. Competing writes at the same expected revision allow exactly one winner and return `revision-conflict` to the other writer. The transition table permits explicit lifecycle progress and rejects mutation after `succeeded`, `cancelled`, or `failed`. A terminal event is valid only when cleanup is complete, so incomplete jobs stay visible to the recovery scan.

`InMemoryJobStateStore` remains a non-durable contract double. `SQLiteJobStateStore` is an inactive file-backed candidate that runs the same conformance suite and adds schema v1, migration refusal, append-only retention, lock redaction, and separate-process hard-exit tests. The running broker is not wired to either store. PostgreSQL, automatic compaction, backup and restore, distributed leases, power-loss qualification, and product activation are not implemented or claimed.

## Verification and remaining gates

The Python 3.12 to 3.14 suite contains 77 tests. The new cases exercise all eleven cancellation checkpoints, wrong-identity and non-boolean signals, four concurrent reconciliations sharing one coordinator, already-absent runtime responses, cancel/reconcile convergence, monotonic revisions, identical replay, conflicting event reuse, concurrent CAS, transition rejection, terminal immutability, recovery pagination, and persisted-shape redaction.

Product Docker and Podman adapters, runtime sockets, broker service transport, live broker-to-store wiring, distributed cleanup ownership, power-loss durability, restart-safe cancellation transport, and solver execution remain blocked or pending under the existing gates. See [event mapping, adapter conformance, and restart recovery](event-state-recovery.md) and the [SQLite durable-state candidate](sqlite-durable-state.md) for the tested contracts.
