# M2 inactive live-state composition

[한국어](../../ko/m2/live-state-composition.md) | [M2 status](README.md)

## Status and authority

- Status: inactive, mock-only composition candidate with contract tests
- Product activation flag: `false`
- Product Docker and Podman runtime kinds: rejected at construction
- Service, worker, runtime socket, network, and solver authority: none
- Phase-time execution persistence: implemented through explicit opt-in composition
- Durable external cancellation: implemented only through the explicit composition; direct `SandboxBroker.cancel()` remains non-persisted

`DurableBrokerComposition` connects the existing broker lifecycle to `DurableJobStateStore` without making that connection the product execution path. Direct `SandboxBroker.execute()` and `SandboxBroker.cancel()` retain their prior in-memory event behavior. The composition accepts only `RuntimeKind.MOCK`, so adding a future product backend cannot implicitly activate this candidate.

## Startup before admission

One serialized `startup()` call must complete before `execute()` or durable `cancel()` admits work:

1. scan one bounded page of recoverable snapshots;
2. use a deterministic page recovery UUID to claim each revision with compare-and-swap;
3. reconcile runtime objects for each exact job identity;
4. continue through all cursors;
5. perform a final one-item recoverable scan; and
6. publish readiness only when that final scan is empty.

An incomplete reconciliation leaves the job in `cleaning` and keeps the admission gate closed. Store failures become the stable redacted `store-unavailable` composition error. Repeated startup calls after readiness return the first completed report. The admission gate remains single-process. The durable store separately enforces bounded owner leases: startup recovery reports `owner-active` and remains closed while any prior owner is live, then claims only after expiry. Guarded runtime awaits renew the exact generation before, during, and after the call. This is a local liveness contract, not a distributed or multi-host lease.

## Phase-time ordering

`LiveStateSession` binds one admitted job, one canonical operation UUID, one normalized backend, and one expected revision. It generates the same deterministic UUID v5 event IDs as `BrokerStateMapper` and awaits each compare-and-swap append.

| Durable event | Must commit before |
| --- | --- |
| `validating` | runtime probe |
| `preparing` | image check and volume allocation |
| `running` | runtime wait |
| `collecting` | artifact transfer and validation |
| `cancelling` | execution-path cancellation kill |
| `cleaning` | object cleanup |
| terminal state | returning the final outcome |

The composition loads state before creating a session. Execution rejects any existing snapshot before runtime probe. Durable cancellation instead requires an existing nonterminal state, rejects an existing cancellation or cleanup intent, and commits `cancelling/query` before runtime query. Concurrent operation IDs are protected by revision CAS. Phase-time records contain only normalized state, phase, code, retry, backend, classification, and cleanup completion fields.

## Partial-write behavior

The first state-store failure marks the session failed. Later phase emissions become no-ops so a broken store cannot prevent the broker's `finally` cleanup path.

| Failure point | Execution behavior | Durable result |
| --- | --- | --- |
| Before `preparing` commit | No image or volume allocation begins | Last committed `validating` revision remains recoverable |
| Before `running` commit | Further execution stops and allocated objects are removed | Last committed `preparing` revision remains recoverable |
| Cleanup or terminal commit | Cleanup still runs | Last committed nonterminal prefix remains recoverable |
| Successful run whose terminal commit fails | Public success is downgraded to `failed` and artifacts are cleared | Committed `cleaning` prefix is closed by startup recovery as `failed:stale-state` |

Public state-write failure uses `invalid-state`, an infrastructure retry disposition, the failed phase, and the normalized mock backend. Driver messages and database paths are not copied into the public outcome. Recovery never synthesizes success.

When runtime cleanup itself is incomplete, the public final event may be `failed`, but the durable final append stays at coded `cleaning`. This preserves visibility to the recovery scan and matches the complete-outcome mapper contract.

## Evidence and remaining gates

Nine execution-composition tests cover startup admission ordering, SQLite phase ordering and owner-aware mapper equivalence, write failures, restart convergence, existing-job refusal, stale-object reconciliation, incomplete-recovery gate closure, and product-runtime rejection. Eight durable cancellation tests cover single-winner CAS, intent-before-query ordering, already-absent convergence, write failures, and five restart checkpoints. Five ownership tests add execution, cancellation, and recovery takeover competition. Four owner-lease and runtime-fencing tests add heartbeat renewal, expiry cancellation, stale-token enforcement, and cross-job rejection. The complete dependency-free Python suite contains 113 tests and invokes no product runtime or solver.

The implemented ownership boundary is documented in [durable operation ownership and fencing](durable-operation-ownership.md) and [owner lease, liveness, and runtime fencing](owner-lease-runtime-fencing.md). Product service transport, worker integration, native product-runtime token persistence and enforcement, multi-host coordination, clock-skew policy, retention compaction, backup and restore, host power-loss qualification, runtime sockets, and solver execution remain blocked or pending.
