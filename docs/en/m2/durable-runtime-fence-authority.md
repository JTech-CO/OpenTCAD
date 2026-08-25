# M2 durable runtime fence authority and activation recovery

[한국어](../../ko/m2/durable-runtime-fence-authority.md) | [M2 status](README.md)

- Status: cross-process local candidate tested, product disabled
- Authority adapter: dedicated SQLite schema v1
- Accepted runtime: strict mock only
- Product Docker and Podman adapters: not implemented

## Authority boundary

`SQLiteRuntimeFenceAuthority` is an inactive implementation of the existing `RuntimeFenceAuthority` protocol. It stores one current tuple per canonical job UUID: owner UUID and positive fencing token. `activate()` is idempotent for the exact tuple, replaces it only with a higher token, and rejects a lower token or the same token paired with another owner using stable `operation-fenced`. `verify()` accepts only the exact current tuple.

The authority uses a dedicated local file, schema version 1, WAL, `synchronous=FULL`, exact schema validation, and `BEGIN IMMEDIATE` for activation. Different processes and different adapter instances therefore serialize generation changes at the SQLite write boundary. Unknown schema, a locked database beyond the bounded timeout, and filesystem or SQLite failures become redacted `runtime-unavailable` with the fixed detail `runtime-fence-authority-unavailable`. Public errors and `repr` do not reveal the database path.

This database is deliberately separate from the schema-v3 broker state database. Sharing a filesystem does not make the two commits atomic.

## Store-to-runtime activation bridge

`DurableRuntimeFenceActivator` joins an exact `DurableOperationOwnership` to the same authority exposed by `RuntimeBackend.fence_authority`. Before guarded runtime contact it performs this sequence:

1. verify the exact live owner tuple and job revision in `DurableJobStateStore`;
2. monotonically activate the matching `RuntimeFencingContext` in the runtime authority;
3. verify the exact store ownership and revision again;
4. verify that the authority still contains the same runtime fence.

`LiveStateSession` uses the bridge for durable execution and cancellation. `DurableOperationGuard` uses it for restart recovery. The mock-only `DurableBrokerComposition` supplies one bridge to all three paths. Existing lease renewal still occurs before activation and the heartbeat continues around the guarded await. A takeover inserted between the first store check and authority activation is caught by the second store check before the runtime operation is entered. A newer authority generation also rejects the stale caller directly.

This double-check is fail-closed but is not a distributed transaction. A takeover may commit after the final check, and a process may terminate after the state commit but before authority activation. Product correctness must not treat the bridge as atomic.

## Crash and restart contract

The activation seams have these recovery rules:

| Seam | Durable observation | Restart action |
|---|---|---|
| Before ownership commit | No new owner generation | Retry normal admission or recovery |
| After ownership commit, before authority activation | State token is ahead of authority token | Wait for or expire the committed lease, claim the next token, then replay activation before reconciliation |
| After authority activation, before runtime contact | Exact state and authority tuple exist | Replay the same activation idempotently |
| During a concurrent takeover | One store or authority post-check fails | Return fenced and perform no stale runtime contact |

A separate Python process commits authority token 2 and calls `os._exit`; a reopened authority retains token 2 and fences the parent at token 1. A second hard-exit test commits a recovery claim at token 2 without activating it. After reopen, recovery claims token 3, activates token 3 before reconciliation, closes the job, and permanently rejects the abandoned token 2. The authority never invents broker state and recovery never lowers an authority token.

## Reusable evidence

`RuntimeFenceAuthorityConformanceMixin` supplies four unchanged cases for exact replay, monotonic replacement, same-token owner ambiguity, and concurrent generation serialization. The SQLite concrete suite adds exact WAL/FULL schema checks, reopen durability, redacted lock and schema failures, and separate-process hard-exit persistence. Four bridge tests cover exact committed ownership, an interleaved takeover at the activation seam, composition execution wiring, and the state-ahead-of-authority restart gap.

The full runtime and broker suite contains 133 tests. It opens no runtime socket, starts no solver, and uses only isolated temporary SQLite files.

## Product gate

This candidate is local-host evidence only. It has no retention, backup, restore, corruption repair, multi-host consensus, bounded clock-skew proof, filesystem power-loss qualification, or product service wiring. It does not revoke an already submitted native call. A product Docker or Podman adapter must persist and enforce the same generation on native objects, use the same authority instance exposed to the composition, pass both reusable conformance suites unchanged, and provide native crash, power-loss, and safe in-flight convergence evidence before activation.
