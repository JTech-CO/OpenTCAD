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

The strict mock adapter retains the highest accepted generation for each job. It rejects a lower token, the same token with a different owner, and a context used with a cross-job handle. It rechecks the bound context around each job operation. Advancing cancellation or recovery therefore fences later calls from an older execution even if the older broker bypassed its store guard.

The mock backend still exposes raw lifecycle methods only as an unbound test-seeding surface. They are not part of the `RuntimeBackend` product protocol, and the broker does not call them for a job lifecycle.

## SQLite migration and recovery

Schema v3 accepts exact schema v1 and v2 files through a forward-only `BEGIN IMMEDIATE` migration. Existing events and owner generations are preserved. A legacy row receives an expiry of `1`, so the migrated owner is conservatively expired and must be claimed by recovery before further work. Unknown or mismatched schemas continue to fail closed.

The common memory and SQLite adapter conformance suite now has ten cases, including revision-neutral renewal, expired-owner rejection, live-owner recovery refusal, cancellation preemption, and expired recovery takeover. Dedicated tests cover heartbeat renewal, cancellation of an expired in-flight awaitable, lower-token rejection, same-token owner ambiguity, cross-job contexts, schema v2 migration, and hard-exit takeover. The dependency-free backend suite contains 113 tests.

## Deliberate limits

This is durable liveness and runtime enforcement for the inactive local candidate and strict mock adapter, not proof for a product OCI adapter or distributed system. Store commit and runtime token activation are not one atomic operation. Cancelling a Python task does not prove that an already submitted native runtime request was revoked. The mock token registry is process memory; no Docker or Podman object currently persists or enforces the three labels.

The system clock can move and independently configured hosts can disagree. There is no database service, clock-skew bound, multi-host lease, quorum, product adapter qualification, power-loss qualification, or backup and restore proof. A future Docker or Podman adapter must persist the owner and token on managed objects, compare them before every mutation, reject stale native requests, and pass native-platform fault evidence before this gate can be promoted.
