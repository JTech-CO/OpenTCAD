# M2 durable external cancellation arbitration

[한국어](../../ko/m2/durable-cancellation-arbitration.md) | [M2 status](README.md)

- Status: candidate contract tested, product disabled
- Work items: RUN-007, BRK-006, BRK-007, and BRK-008 extension
- Runtime authority: mock only

This slice connects typed external cancellation to the existing durable-state candidate without adding HTTP, IPC, a worker, a product runtime adapter, a runtime socket, or solver execution. `DurableBrokerComposition.cancel()` is the only persisted cancellation entry point. Direct `SandboxBroker.cancel()` deliberately retains its earlier non-persisted contract.

## Admission and single-winner arbitration

Cancellation follows this order:

1. Startup recovery must have completed and admission must be open.
2. The composition loads the exact `JobIdentity` from `DurableJobStateStore` before contacting the runtime.
3. Missing state, terminal state, and an existing `cancelling` or `cleaning` state are rejected with stable composition errors.
4. A caller-specific logical operation UUID and fresh internal owner UUID open a `LiveStateSession` at the loaded revision with the next fencing token.
5. The session appends `cancelling/query` with compare-and-swap. This committed event is both durable cancellation intent and ownership takeover.
6. Only the CAS winner may query or mutate runtime objects. A competing operation ID receives `cancellation-conflict` and makes no runtime call.

The process-local cleanup coordinator avoids duplicate mutation inside one broker. Correctness across independent broker instances comes from store CAS, the committed owner generation, and its bounded durable lease. Heartbeats renew the exact generation without advancing the job revision. Cancellation is the only operation allowed to preempt a live lease: it commits the next token before runtime contact, while recovery must report `owner-active` until the prior lease expires. This remains a single-machine candidate, not a distributed or multi-host lease.

## Persisted lifecycle

For a running container, the candidate path records these boundaries in order:

| Boundary | Durable state and phase | Ordering guarantee |
|---|---|---|
| Intent | `cancelling/query` | Committed before the first runtime query |
| Kill authorization | `cancelling/kill` | Committed before cancellation kill |
| Cleanup intent | `cleaning/cleanup` with cancelled classification | Recorded before cleanup |
| Terminal | `cancelled/kill` | Recorded only after exact-job cleanup and a zero-object recheck |

If the runtime container and volume are already absent, the committed intent converges through `cleaning` to `cancelled` without inventing a `RunResult`. A volume-only prefix is removed and converges the same way. This idempotent convergence is available only after durable intent admission; direct broker cancellation keeps its prior missing-container behavior.

The complete-outcome mapper treats every `CancellationOutcome` as cancellation intent. Therefore an incomplete-cleanup mapping remains recoverable as `cleaning` with cancelled classification instead of losing the cancellation decision.

## Write failures and public results

- If the intent append fails, runtime contact is forbidden. Store unavailability is reported as `store-unavailable`; a CAS or transition loss is reported as `cancellation-conflict`.
- If a later phase append fails for ordinary store unavailability, cancellation progress stops but fail-safe cleanup continues. If the owner or revision was superseded, the public outcome is `failed:operation-fenced`, stale cleanup is skipped, and the current owner's prefix remains authoritative and recoverable.
- If the terminal append fails after runtime cancellation and cleanup, the public outcome is still `failed`. A cancelled runtime result alone is not enough to report durable completion.
- Restart recovery never synthesizes `succeeded`. A committed cancellation intent closes as `cancelled`; an unacknowledged running prefix closes as `failed:stale-state`.

No raw database, filesystem, runtime, or driver detail enters the public outcome.

## Crash and restart contract

Five deterministic checkpoints model interruption of the cancellation operation:

| Injected checkpoint | Last committed state | Restart result |
|---|---|---|
| `before-intent` | `running` | `failed:stale-state` after reconciliation |
| `after-intent` | `cancelling` | `cancelled` after reconciliation |
| `after-cleaning-state` | `cleaning` | `cancelled` after reconciliation |
| `after-cleanup` | `cleaning`, zero objects | `cancelled` |
| `after-final-state` | `cancelled` | Already terminal and excluded from recovery scan |

The checkpoint exception is a deterministic same-process crash surrogate for contract tests. It does not claim that external cancellation itself has been tested with an OS process hard exit or host power loss. The separate SQLite recovery suite still supplies the existing committed-claim hard-exit proof.

## Verification and remaining gates

Eight focused cancellation tests cover admission refusal, SQLite ordering and owner-aware mapper equivalence, already-absent convergence, two independent broker callers with one CAS winner, intent-write failure, later phase-write failure, terminal-write failure, and all five restart checkpoints. Five additional ownership competition tests cover cancellation takeover and stale-owner fencing. Four owner-lease and runtime-fencing tests additionally cover revision-neutral heartbeat renewal, expiry cancellation, stale and ambiguous token rejection, and cross-job context rejection. The complete dependency-free Python suite contains 140 tests and opens no product runtime socket, network connection, or solver.

The implemented takeover rules are detailed in [durable operation ownership and fencing](durable-operation-ownership.md) and [owner lease, liveness, and runtime fencing](owner-lease-runtime-fencing.md). Product service transport, worker integration, native Docker and Podman token persistence and enforcement, runtime detection, native in-flight revocation, product backup scheduling, authenticated restore admission, durable rollback-floor storage, power-loss qualification, clock-skew policy, multi-host coordination, runtime sockets, and solver execution remain blocked or pending.
