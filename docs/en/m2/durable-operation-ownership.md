# M2 durable operation ownership and fencing

[한국어](../../ko/m2/durable-operation-ownership.md) | [M2 status](README.md)

- Status: candidate contract tested, product disabled
- Operations: execution, external cancellation, and restart recovery
- Authority: durable lease checks plus strict bound mock-runtime enforcement only

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

`LiveStateSession` renews the exact live ownership before, during, and after guarded runtime awaits. Probe and image preparation remain global operations but are still heartbeat guarded. Every job lifecycle call for volume creation, input staging, container creation, start, wait, artifact collection, kill, cleanup mutation, and exact-job zero-object query is made through `RuntimeBackend.bind_job()` with the guard's exact `RuntimeFencingContext`. Durable cancellation binds its committed takeover before query and kill. Recovery can claim only an expired lease, then uses the same bound context for reconciliation.

If a stale or expired execution or cancellation loses renewal, its Python awaitable is cancelled, it returns public `failed` with stable `operation-fenced`, skips stale cleanup mutation, and cannot append a durable terminal state. The strict mock runtime independently rejects a lower token, the same token paired with another owner, a cross-job context, or a handle from another job. A stale recovery item reports `ownership-conflict`; a live previous lease reports `owner-active` without takeover. No raw database or runtime detail is exposed.

## SQLite schema and compatibility

The inactive SQLite candidate now uses schema version `3`. Append-only `job_events` rows retain each committed lease duration, while one mutable `job_leases` row stores the current owner tuple and absolute expiry. `renew_ownership()` updates only that exact live lease row, so heartbeat renewal does not change a job revision or append a durable event. Append, renew, verify, and recovery scan enforce the same expiry and ownership rules as the memory double.

Existing exact schema version `1` files migrate through version `2` to version `3` in one transaction without deleting events; exact version `2` files migrate directly to version `3`. Historical operation generations are preserved and receive a conservatively expired current lease so recovery may make progress after upgrade. Unknown forward versions and mismatched event or lease tables still fail closed. Automatic downgrade, compaction, backup, and restore are not implemented.

## Competition evidence

Five focused tests exercise cross-operation ownership:

1. Two execution callers with one logical operation UUID produce one runtime caller and one fenced loser.
2. Cancellation takes over a live execution and prevents the stale execution from entering wait or cleanup.
3. Ownership transferred just before an execution-local cancellation prevents the stale owner from killing or cleaning runtime objects.
4. Recovery takes over a cancellation before its runtime query, so only recovery mutates the mock runtime.
5. A newer recovery fences an older reconciler before the older owner can mutate runtime objects.

Four owner-lease tests prove revision-neutral heartbeat renewal, cancellation of an expired in-flight Python awaitable, stale and ambiguous owner rejection, and cross-job rejection. The reusable runtime-fence suite adds five common adapter cases plus three focused authority, parser, and post-mutation cases. These prove exact mock-object label persistence, shared authority across adapter instances, takeover restrictions, post-operation stale-result suppression, and cleanup convergence. The complete dependency-free Python suite contains 133 tests. It invokes no product runtime, network service, runtime socket, or solver.

## Exact limitation and next boundary

The inactive local candidate now has durable heartbeat liveness, lease expiry, a process-local reference authority, a dedicated SQLite cross-process authority candidate, a double-checked store-to-runtime activation bridge, and native-object fencing enforcement in the strict mock adapter. Store commit and runtime activation are not one atomic action. Cancelling a Python awaitable does not prove that a previously submitted native runtime request was revoked. A post-operation check suppresses stale success and permits current-owner cleanup convergence, but it cannot undo a completed mutation. Object metadata remains strict mock evidence; no Docker or Podman object persists or enforces the labels. There is no bounded clock-skew contract, multi-host lock or authority, database service, power-loss qualification, or product adapter integration.

The next ownership boundary is a reviewed Docker or Podman adapter that exposes the common authority, implements the object-label contract, passes both reusable suites unchanged, and produces explicit native-platform evidence for in-flight revocation or safe convergence. See [owner lease, liveness, and runtime fencing](owner-lease-runtime-fencing.md), [native-object runtime fencing conformance](native-runtime-fence-conformance.md), and [durable runtime fence authority and activation recovery](durable-runtime-fence-authority.md). Product work remains gated by the immutable engine profile, M1 evidence, product-adapter review, and the existing no-socket product boundary.
