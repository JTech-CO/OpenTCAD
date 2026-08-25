# M2 event mapping, adapter conformance, and restart recovery

[한국어](../../ko/m2/event-state-recovery.md) | [M2 status](README.md)

## Status and scope

- Status: engine-independent contract implementation, gated
- Runtime and solver access: none
- SQLite durable-state candidate: tested and inactive
- Phase-time execution wiring: implemented in an inactive mock-only composition
- External cancellation wiring: implemented in the inactive mock-only composition, product disabled

This contract defines how a completed redacted broker operation becomes durable events, how every state adapter is tested, and how recoverable state converges after restart. The original mapping and recovery seams remain engine-independent; the companion SQLite candidate adds only a standard-library local database and a test-only child process. It adds no service transport, runtime socket, product Docker or Podman adapter, worker integration, or solver execution.

## Broker event to durable state mapping

`BrokerStateMapper` accepts a `BrokerOutcome` or `CancellationOutcome` plus a canonical operation UUID, normalized runtime kind, owner-attempt UUID, and fencing token. The complete-outcome default uses the operation UUID as owner with token 1; phase-time composition supplies the actual admitted owner generation. The source event sequence must be exactly `1..N`, its final state must equal the outcome state, and every coded source event must match a redacted `BrokerError`. A normalized error backend that conflicts with the mapping context fails closed.

| Source or context | Durable field or rule |
| --- | --- |
| Exact job identity | `job_id` and the complete `JobIdentity` |
| Operation UUID | `operation_id` and UUID v5 namespace |
| Owner generation | `owner_id` and positive `fencing_token` on every event |
| `BrokerEvent.sequence` | Positive `operation_sequence` |
| Job ID plus source sequence | Deterministic UUID v5 `event_id` |
| Broker state and phase | `state` and `phase` |
| Matched public error | Stable `code` and `retry` only |
| Mapping context | Normalized `backend` |
| Redacted run result or cancellation intent | `classification` only where the state contract permits it |
| Terminal state | Valid only when cleanup is complete |

The adapter rejects reuse of either an event UUID with different content or a `(job_id, operation_id, operation_sequence)` slot with a different event. `StateEventRecorder` appends a batch with compare-and-swap revisions. Deterministic IDs make an identical replay return the original committed snapshots, so a recorder can resume after only part of a batch was committed.

An outcome with incomplete cleanup is never persisted as terminal. Its final source terminal event is mapped to another recoverable `cleaning` event with phase `cleanup` and the stable cleanup error. This prevents an orphaned runtime object from disappearing from the recovery scan merely because the broker had already selected `failed` for its public outcome.

This mapper continues to consume complete outcomes. `LiveStateSession` reuses its deterministic identity rules while `DurableBrokerComposition` awaits execution and external-cancellation appends as work occurs. External cancellation records `cancelling/query` with the next owner generation before runtime query and retains cancelled classification through cleanup. Recovery likewise claims the next generation before reconciliation. The explicit path is mock-only and product-disabled; direct broker execution and cancellation are not persisted.

## Common adapter conformance suite

`DurableStateStoreConformanceMixin` is the reusable suite for every future durable adapter. A concrete adapter supplies a new handle and a reopened handle over the same committed storage. The suite verifies:

1. protocol shape, empty load, and empty scan;
2. legal monotonic transitions and commit visibility after adapter reopen;
3. identical replay after reopen;
4. event UUID and operation-slot conflict rejection;
5. exactly one compare-and-swap winner from one revision;
6. bounded, sorted recovery pagination that excludes terminal jobs; and
7. owner takeover after reopen followed by rejection of the stale token.

The seven-case suite now runs unchanged against two concrete adapters. `InMemoryStateStoreBacking` still proves process-local handle semantics only. `SQLiteJobStateStore` proves file-backed commit visibility, transactional CAS and ownership transfer, stale-token rejection after reopen, schema fail-closed behavior, database-lock redaction, and recovery pagination through fresh handles. The [SQLite durable-state candidate contract](sqlite-durable-state.md) records the distinct migration, retention, and durability limits.

## Crash and restart recovery contract

`CrashRecoveryCoordinator` processes one bounded recovery page:

1. scan nonterminal snapshots;
2. append a `cleaning` claim with a fresh owner UUID, the next fencing token, and compare-and-swap;
3. reconcile runtime objects for the exact job identity;
4. leave a coded `cleaning` event when reconciliation is incomplete; or
5. append `cancelled` when cancellation intent survived, otherwise append fail-safe `failed` with `stale-state`.

A restarted job is never reconstructed as `succeeded`. Success requires the normal broker path and validated artifacts. Recovery only removes stale objects and closes or retains durable state.

The deterministic crash surrogate covers four boundaries:

| Injected boundary | Durable state at interruption | Mock runtime objects | Restart behavior |
| --- | --- | --- | --- |
| Before claim | Original recoverable revision | Unchanged | Claim, reconcile, close |
| After claim | `cleaning` claim committed | Unchanged | New owner generation takes over, reconciles, closes |
| After reconcile | `cleaning` claim committed | Zero after a complete reconciliation | New owner generation takes over, verifies, closes |
| After terminal append | Terminal revision committed | Zero | Recovery scan excludes the job |

The deterministic tests reopen a fresh state-store handle over the same fixture after every injected interruption. `recovery_id` remains report correlation, while each recovery pass uses a fresh owner attempt. A restart takes over the last nonterminal generation by incrementing its token; incomplete cleanup remains recoverable for another owner attempt. In addition, a child process commits SQLite revision 4 at `after-claim` and terminates with `os._exit(91)`. The parent reopens the file, commits a fresh recovery owner at revision 5, and converges to terminal revision 6.

Compare-and-swap permits exactly one claimant when concurrent coordinators read the same revision. A later recovery may take over a nonterminal `cleaning` owner only with the next fencing token, and the previous reconciler is rejected at its next guard. This is cooperative durable ownership, not a distributed lease or runtime-enforced fence: owner liveness, lease expiry, multi-host coordination, and atomic coupling between verification and runtime mutation remain unimplemented.

## Evidence and remaining gate

The dependency-free Python suite now contains 102 tests. It covers the seven-case common suite on memory and SQLite adapters, owner-aware outcome and phase-time mapping, partial replay, startup admission, partial-write cleanup, four recovery crash boundaries, five cancellation crash boundaries, five execution/cancellation/recovery ownership competitions, cancellation recovery, competing claims, cleanup retry convergence, schema-v1 migration, lock behavior, and the separate-process hard exit. Tests open isolated SQLite files only; no test opens a runtime socket, network connection, product runtime, or solver.

The implemented ownership contract is detailed in [durable operation ownership and fencing](durable-operation-ownership.md). Durable owner liveness, lease expiry, runtime-enforced token propagation, backup and restore, power-loss qualification, multi-host coordination, product activation, and product Docker and Podman adapters remain gated.
