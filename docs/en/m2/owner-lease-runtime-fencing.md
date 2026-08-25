# M2 owner lease, liveness, and runtime fencing

## Scope

This slice extends the inactive mock-only durable composition. It does not add a Docker or Podman product adapter, runtime socket access, a broker service, a worker, or solver execution. The SQLite candidate and strict mock runtime remain product-disabled.

## Durable owner lease

Each committed owner generation receives a bounded lease. The default duration is 30,000 milliseconds, the default heartbeat interval is 10,000 milliseconds, and the hard maximum duration is 300,000 milliseconds. State adapters own the UTC epoch-millisecond clock used to decide whether `now < lease_expires_at_ms`.

The immutable `job_events` audit log records the requested lease duration and the expiry resolved at each event commit. Schema v3 adds a separate `job_leases` control table for the current owner, job revision, and expiry. `renew_ownership()` updates only that exact control row under the adapter transaction. It does not create a broker event or advance the job revision.

Renewal requires the exact job, operation, owner, fencing token, and job revision. An expired owner cannot verify, renew, append another event, or revive its generation. Cancellation is an explicit preemption and may advance to the next token while the execution lease is live. Recovery may advance to `cleaning` only after the previous lease expires. A recovery scan that observes a live generation reports `owner-active` and leaves startup admission closed.

Every guarded runtime await is wrapped by the owner heartbeat. The guard renews before the call, periodically while it is pending, and once after completion. If renewal loses ownership or observes expiry, the Python awaitable is cancelled and the broker reports `operation-fenced`.

## Runtime adapter fence

`RuntimeBackend.bind_job(RuntimeFencingContext)` is the only broker-facing job lifecycle entry. It returns a `RuntimeJobBackend` bound to one job UUID, owner UUID, and positive fencing token. The context provides the future OCI metadata labels `tcad.job_id`, `tcad.owner_id`, and `tcad.fencing_token`. `runtime_fencing` is a required fail-closed runtime capability.

The mock adapter receives a `RuntimeFenceAuthority`. The process-local reference and the dedicated SQLite cross-process candidate both retain the highest activated generation per job. `DurableRuntimeFenceActivator` verifies the exact live store owner and revision, activates the same runtime context, then rechecks both boundaries before runtime contact. Every bound call also activates immediately before adapter work and verifies immediately after return. Managed mock volumes and containers persist the exact job, owner, and token labels; every operation reconstructs and checks the observed context. Normal lifecycle work requires an exact generation, while a higher takeover may only query, kill, or clean predecessor objects. Lower tokens, same-token owner ambiguity, malformed labels, cross-job contexts, and mismatched handles fail closed.

The mock backend still exposes raw lifecycle methods only as an unbound test-seeding surface. They are not part of the `RuntimeBackend` product protocol, and the broker does not call them for a job lifecycle.

## SQLite migration and recovery

Schema v3 accepts exact schema v1 and v2 files through a forward-only `BEGIN IMMEDIATE` migration. Existing events and owner generations are preserved. A legacy row receives an expiry of `1`, so the migrated owner is conservatively expired and must be claimed by recovery before further work. Unknown or mismatched schemas continue to fail closed.

The common memory and SQLite state-adapter conformance suite has ten cases. The reusable runtime-fence suite adds five common adapter cases for label persistence, shared-authority fencing, owner ambiguity, takeover restrictions, and cross-job rejection. Three focused cases cover malformed labels, verification before activation, and post-mutation stale-result suppression followed by current-owner cleanup convergence. Dedicated lease and recovery tests continue to cover heartbeat renewal, cancellation of an expired in-flight awaitable, schema v2 migration, and hard-exit takeover. The dependency-free backend suite contains 133 tests.

## Deliberate limits

This is durable liveness plus local cross-process authority and native-object contract enforcement for the inactive candidate and strict mock adapter, not proof for a product OCI adapter or distributed system. Store commit and runtime activation are not one atomic operation, and the authority database is separate from broker state. A submitted native operation may complete a mutation after takeover; the post-operation check suppresses its stale result and current-owner cleanup can converge, but this does not prove native revocation or rollback. Mock object metadata is not Docker or Podman metadata.

The system clock can move and independently configured hosts can disagree. There is no database service, multi-host authority or lease, clock-skew bound, quorum, product adapter qualification, power-loss qualification, or backup and restore proof. The local SQLite candidate and activation-gap recovery are detailed in [durable runtime fence authority and activation recovery](durable-runtime-fence-authority.md). A future Docker or Podman adapter must implement the same label, authority, inspection, and operation rules, pass both common suites unchanged, and produce native-platform fault evidence before this gate can be promoted.
