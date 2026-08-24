# M2 event mapping, adapter conformance, and restart recovery

[한국어](../../ko/m2/event-state-recovery.md) | [M2 status](README.md)

## Status and scope

- Status: engine-independent contract implementation, gated
- Runtime and solver access: none
- Durable database adapter: not implemented
- Live broker-to-store wiring: not implemented

This slice defines how a completed redacted broker operation becomes durable events, how every future state adapter must be tested, and how recoverable state converges after a process restart. It uses only strict in-memory doubles. It does not add a service transport, database driver, runtime socket, product Docker or Podman adapter, worker integration, or solver execution.

## Broker event to durable state mapping

`BrokerStateMapper` accepts a `BrokerOutcome` or `CancellationOutcome` plus a canonical operation UUID and normalized runtime kind. The source event sequence must be exactly `1..N`, its final state must equal the outcome state, and every coded source event must match a redacted `BrokerError`. A normalized error backend that conflicts with the mapping context fails closed.

| Source or context | Durable field or rule |
| --- | --- |
| Exact job identity | `job_id` and the complete `JobIdentity` |
| Operation UUID | `operation_id` and UUID v5 namespace |
| `BrokerEvent.sequence` | Positive `operation_sequence` |
| Job ID plus source sequence | Deterministic UUID v5 `event_id` |
| Broker state and phase | `state` and `phase` |
| Matched public error | Stable `code` and `retry` only |
| Mapping context | Normalized `backend` |
| Redacted run result or cancellation intent | `classification` only where the state contract permits it |
| Terminal state | Valid only when cleanup is complete |

The adapter rejects reuse of either an event UUID with different content or a `(job_id, operation_id, operation_sequence)` slot with a different event. `StateEventRecorder` appends a batch with compare-and-swap revisions. Deterministic IDs make an identical replay return the original committed snapshots, so a recorder can resume after only part of a batch was committed.

An outcome with incomplete cleanup is never persisted as terminal. Its final source terminal event is mapped to another recoverable `cleaning` event with phase `cleanup` and the stable cleanup error. This prevents an orphaned runtime object from disappearing from the recovery scan merely because the broker had already selected `failed` for its public outcome.

This mapper consumes complete outcomes. It does not yet make the running broker append events as phases occur. Live broker-to-store wiring remains a separate gate.

## Common adapter conformance suite

`DurableStateStoreConformanceMixin` is the reusable suite for every future durable adapter. A concrete adapter supplies a new handle and a reopened handle over the same committed storage. The suite verifies:

1. protocol shape, empty load, and empty scan;
2. legal monotonic transitions and commit visibility after adapter reopen;
3. identical replay after reopen;
4. event UUID and operation-slot conflict rejection;
5. exactly one compare-and-swap winner from one revision; and
6. bounded, sorted recovery pagination that excludes terminal jobs.

The current concrete run uses `InMemoryStateStoreBacking` so separate adapter handles can share one process-local fixture. This proves the suite and handle-reopen semantics only. The backing is lost with the process and does not prove crash durability, transaction isolation, migration safety, backup, retention, or database availability behavior.

## Crash and restart recovery contract

`CrashRecoveryCoordinator` processes one bounded recovery page:

1. scan nonterminal snapshots;
2. append a deterministic `cleaning` claim with compare-and-swap;
3. reconcile runtime objects for the exact job identity;
4. leave a coded `cleaning` event when reconciliation is incomplete; or
5. append `cancelled` when cancellation intent survived, otherwise append fail-safe `failed` with `stale-state`.

A restarted job is never reconstructed as `succeeded`. Success requires the normal broker path and validated artifacts. Recovery only removes stale objects and closes or retains durable state.

The deterministic crash surrogate covers four boundaries:

| Injected boundary | Durable state at interruption | Mock runtime objects | Restart behavior |
| --- | --- | --- | --- |
| Before claim | Original recoverable revision | Unchanged | Claim, reconcile, close |
| After claim | `cleaning` claim committed | Unchanged | Replay claim, reconcile, close |
| After reconcile | `cleaning` claim committed | Zero after a complete reconciliation | Replay claim, verify, close |
| After terminal append | Terminal revision committed | Zero | Recovery scan excludes the job |

The tests reopen a fresh state-store handle over the same fixture after every injected interruption. The same recovery UUID safely replays an already committed claim. An incomplete cleanup remains recoverable and a later recovery UUID can retry it.

Compare-and-swap permits exactly one claimant when concurrent coordinators read the same revision. This is not a distributed lease: a later scan can observe a newer `cleaning` revision, and multi-process ownership, lease expiry, fencing tokens, and database-backed arbitration remain unimplemented.

## Evidence and remaining gate

The dependency-free Python suite now contains 67 tests. Fifteen tests cover the common adapter suite, outcome mapping and partial replay, four crash boundaries, cancellation recovery, competing claims, and cleanup retry convergence. No test opens a runtime socket, database, network connection, or solver.

The next state milestone requires selecting and reviewing an actual durable adapter, proving transaction and restart behavior in a separate process, defining migration and retention policy, and then wiring phase-time broker events to that adapter. Product Docker and Podman adapters remain blocked by the existing M2 entry and security gates.
