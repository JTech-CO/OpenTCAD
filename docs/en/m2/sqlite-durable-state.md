# M2 SQLite durable-state candidate

[한국어](../../ko/m2/sqlite-durable-state.md) | [M2 status](README.md)

- Status: candidate adapter and recovery contract tested, not product-enabled
- Work items: RUN-007, BRK-006, BRK-007, and BRK-008 extension
- Runtime, solver, and service authority: unchanged and disabled
- Inactive phase-time composition: mock execution contract tested

## Decision

`SQLiteJobStateStore` is the first file-backed candidate for the existing `DurableJobStateStore` boundary. SQLite is available through the Python standard library on Windows, macOS, and Linux and fits the single-machine local-server target. This decision does not select a multi-host queue. An explicit mock-only composition can open the candidate for contract tests, but direct broker execution and every product path remain disabled.

The constructor accepts only a local file path. It rejects the in-memory database and SQLite URI forms. The database location is an administrator-owned internal setting, not a project archive field, request field, host mount, or sandbox input.

## Transaction and schema contract

Schema version 3 keeps the append-only `job_events` table and adds a mutable `job_leases` control table. Every event row contains the redacted durable fields, `owner_id`, `fencing_token`, bounded `lease_duration_ms`, and committed revision. The current lease row contains the exact job, operation, owner, token, revision, and absolute expiry. The database enforces unique event IDs, unique job-operation-sequence slots, unique job revisions, and one current lease per job. No raw diagnostic, payload, command, secret, runtime-native identifier, or host path is stored.

Each append uses `BEGIN IMMEDIATE`, checks an identical event replay before revision CAS, validates transition, owner-generation, and lease rules, inserts one new revision, updates the current lease, and commits. Concurrent writers therefore serialize at the database boundary and only one writer can satisfy a given expected revision. `renew_ownership()` uses a separate `BEGIN IMMEDIATE` transaction to extend only an exact unexpired lease and deliberately leaves the event log and job revision unchanged. `verify_ownership()` requires the exact live owner tuple and optional revision; this read and a following runtime call are deliberately not claimed as one atomic action. WAL mode and `synchronous=FULL` are required. SQLite and filesystem messages are translated to the stable `store-unavailable` code and are not exposed through public exceptions.

`PRAGMA user_version` is the forward-only migration marker:

1. A new version 0 database is created as the exact version 3 schema in one transaction.
2. An exact version 1 database is migrated through version 2 to version 3 in one transaction without dropping durable events. Historical operations become owner generations ordered by their first revisions, and each prior operation UUID becomes its migrated owner UUID.
3. An exact version 2 database is migrated to version 3 in one transaction; existing events receive the default lease duration and each latest owner receives a conservatively expired lease row.
4. An exact version 3 database is accepted only when both table definitions match.
5. An unknown newer version or a mismatched table definition fails closed.
6. No destructive, downgrade, or best-effort migration runs automatically.

## Common conformance and hard-exit proof

The SQLite candidate runs the unchanged ten-case adapter conformance suite. It proves empty reads, committed visibility through a fresh adapter handle, idempotent replay, event and operation-slot conflicts, concurrent CAS, bounded recovery pagination, stale-token rejection after owner takeover and reopen, revision-neutral lease renewal visible after reopen, expired-owner rejection, live-owner recovery refusal, cancellation preemption, and expired-owner recovery takeover.

A separate Python process opens the file, lets `CrashRecoveryCoordinator` commit a token-2 `cleaning` claim at revision 4, and calls `os._exit(91)` at the `after-claim` checkpoint. A fresh parent-process adapter observes that committed revision. After the deliberately short child lease expires, a new recovery owner takes over with token 3 at revision 5, reconciles the exact job, and closes the job at revision 6 as `failed:stale-state` without synthesizing success.

This is process hard-exit, persisted lease-expiry, and reopened-store ownership-transfer evidence. The separate [coordinated offline snapshot contract](sqlite-offline-snapshot-restore.md) now proves candidate pair backup, fresh-target restore, and recovery continuation. Neither contract claims host power-loss tolerance, filesystem-corruption repair, product backup operation, native product-runtime fencing, bounded clock skew, or multi-host operation.

## Retention and recovery policy

Version 3 performs no automatic deletion or compaction. Lease renewal mutates only the current control row; committed job events remain append-only. Removing old rows would discard event-ID and operation-slot idempotency evidence as well as the audit sequence. A future retention design must preserve the latest snapshot, event-ID tombstones, operation-slot tombstones, revision monotonicity, backup and restore behavior, and recovery scan semantics before deletion can be enabled.

The database remains a candidate test artifact. An explicit mock-only composition writes execution, external-cancellation, recovery, and owner-generation events to it after startup recovery, but direct broker calls and services do not open it. No product runtime or solver operation depends on it.

## Next gate

The implemented store ownership rules are detailed in [durable operation ownership and fencing](durable-operation-ownership.md) and [owner lease, liveness, and runtime fencing](owner-lease-runtime-fencing.md). Native product-runtime token persistence and enforcement, distributed coordination, clock-skew policy, broker-integrated backup admission and protected credential storage, power-loss qualification, product Docker and Podman adapters, runtime sockets, and solver execution remain separate gated work.
