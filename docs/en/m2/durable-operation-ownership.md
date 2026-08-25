# M2 durable operation ownership and fencing

[한국어](../../ko/m2/durable-operation-ownership.md) | [M2 status](README.md)

- Status: candidate contract tested, product disabled
- Operations: execution, external cancellation, and restart recovery
- Authority: durable-store checks with the mock runtime only

This slice gives each admitted operation an explicit durable owner generation. It prevents an owner that has already lost the durable record from continuing at checked broker boundaries. It does not add a service, worker transport, product Docker or Podman adapter, runtime socket, or solver execution.

## Ownership model

`DurableOperationOwnership` contains the exact `JobIdentity`, logical `operation_id`, owner-attempt UUID `owner_id`, and positive integer `fencing_token`. Every durable event stores all four values.

- A newly admitted execution starts with token `1` and a fresh internal owner UUID. Repeated callers with the same logical operation UUID still compete as different owner attempts.
- One owner must retain the same operation UUID and token for all later events.
- A cancellation takeover commits `cancelling` with the immediately following token before any runtime query.
- Recovery commits `cleaning` with the immediately following token before reconciliation. A newer recovery may take over a crashed recovery with another increment.
- A takeover that skips a generation, reuses a token with another owner, changes operation identity without a legal takeover, or starts in any other state fails closed as `ownership-conflict`.

Revision compare-and-swap remains independent from the fencing token. The revision orders every event; the token identifies the current owner generation. `verify_ownership()` requires the exact owner tuple and, when supplied, the exact last observed revision. This also prevents duplicate progress by one owner after another writer has advanced the job.

## Checked boundaries

`LiveStateSession` verifies ownership before execution runtime calls for probe, image preparation, volume creation, input staging, container creation, start, wait, artifact collection, kill, cleanup mutations, and the final zero-object query. Durable cancellation verifies its takeover before query and kill. Recovery wraps reconciliation in `DurableOperationGuard` and checks before its query, each mutation or retry, and its final verification query.

If a stale execution or cancellation detects a different owner or revision, it returns public `failed` with stable `operation-fenced`, skips stale cleanup mutation, and cannot append a durable terminal state. A stale recovery item reports `ownership-conflict` with the same public code. No raw database or runtime detail is exposed.

## SQLite schema and compatibility

The inactive SQLite candidate now uses schema version `2`. The append transaction enforces the same ownership rules as the memory double. `verify_ownership()` reads the latest committed snapshot and requires the exact owner tuple and optional expected revision. The common adapter conformance suite adds a seventh case that reopens an adapter, transfers ownership, and proves that the previous token is fenced.

Existing schema version `1` files are migrated forward in one transaction without deleting events. Each historical operation becomes an owner generation ordered by its first revision. The prior operation UUID is used as its migrated owner UUID. Unknown forward versions and mismatched schemas still fail closed. Automatic downgrade, compaction, backup, and restore are not implemented.

## Competition evidence

Five focused tests exercise cross-operation ownership:

1. Two execution callers with one logical operation UUID produce one runtime caller and one fenced loser.
2. Cancellation takes over a live execution and prevents the stale execution from entering wait or cleanup.
3. Ownership transferred just before an execution-local cancellation prevents the stale owner from killing or cleaning runtime objects.
4. Recovery takes over a cancellation before its runtime query, so only recovery mutates the mock runtime.
5. A newer recovery fences an older reconciler before the older owner can mutate runtime objects.

The complete dependency-free Python suite contains 102 tests. It invokes no product runtime, network service, runtime socket, or solver.

## Exact limitation and next boundary

This is cooperative application-level fencing, not runtime-enforced or distributed fencing. Ownership verification and the following mock-runtime call are not one atomic action. A takeover that occurs after a successful check cannot revoke a call already in flight, and the mock runtime does not validate tokens on objects or mutations. There is no heartbeat, lease expiry, failed-owner detector, multi-host lock, database service, power-loss qualification, or product adapter integration.

The next ownership boundary is durable owner liveness and lease-expiry policy together with propagation and enforcement of fencing tokens at a future product runtime adapter. That work remains gated by the immutable engine profile, M1 evidence, product-adapter review, and the existing no-socket product boundary.
