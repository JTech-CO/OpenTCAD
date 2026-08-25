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

Schema version 2 is an append-only `job_events` table. Each row contains the redacted durable event fields, `owner_id`, `fencing_token`, and its committed revision. The database enforces unique event IDs, unique job-operation-sequence slots, and unique job revisions. No raw diagnostic, payload, command, secret, runtime-native identifier, or host path is stored.

Each append uses `BEGIN IMMEDIATE`, checks an identical event replay before revision CAS, validates the shared transition and owner-generation rules, inserts one new revision, and commits. Concurrent writers therefore serialize at the database boundary and only one writer can satisfy a given expected revision. `verify_ownership()` reads the latest committed snapshot and requires the exact owner tuple and optional revision; this read and a following runtime call are deliberately not claimed as one atomic action. WAL mode and `synchronous=FULL` are required. SQLite and filesystem messages are translated to the stable `store-unavailable` code and are not exposed through public exceptions.

`PRAGMA user_version` is the forward-only migration marker:

1. A new version 0 database is created as the exact version 2 schema in one transaction.
2. An exact version 1 database is migrated to version 2 in one transaction without dropping durable events. Historical operations become owner generations ordered by their first revisions, and each prior operation UUID becomes its migrated owner UUID.
3. An exact version 2 database is accepted.
4. An unknown newer version or a mismatched table definition fails closed.
5. No destructive, downgrade, or best-effort migration runs automatically.

## Common conformance and hard-exit proof

The SQLite candidate runs the unchanged seven-case adapter conformance suite. It proves empty reads, committed visibility through a fresh adapter handle, idempotent replay, event and operation-slot conflicts, concurrent CAS, bounded recovery pagination, and stale-token rejection after owner takeover and reopen.

A separate Python process opens the file, lets `CrashRecoveryCoordinator` commit a token-2 `cleaning` claim at revision 4, and calls `os._exit(91)` at the `after-claim` checkpoint. A fresh parent-process adapter observes that committed revision. A new recovery owner takes over with token 3 at revision 5, reconciles the exact job, and closes the job at revision 6 as `failed:stale-state` without synthesizing success.

This is process hard-exit and reopened-store ownership-transfer evidence. It is not a claim of host power-loss tolerance, filesystem-corruption recovery, backup and restore correctness, owner liveness or lease expiry, runtime-enforced fencing, or multi-host operation.

## Retention and recovery policy

Version 2 performs no automatic deletion or compaction. Removing old rows would discard event-ID and operation-slot idempotency evidence as well as the audit sequence. A future retention design must preserve the latest snapshot, event-ID tombstones, operation-slot tombstones, revision monotonicity, backup and restore behavior, and recovery scan semantics before deletion can be enabled.

The database remains a candidate test artifact. An explicit mock-only composition writes execution, external-cancellation, recovery, and owner-generation events to it after startup recovery, but direct broker calls and services do not open it. No product runtime or solver operation depends on it.

## Next gate

The implemented store ownership rules are detailed in [durable operation ownership and fencing](durable-operation-ownership.md). Durable owner liveness, lease expiry, runtime-enforced token propagation, distributed coordination, backup and restore, power-loss qualification, product Docker and Podman adapters, runtime sockets, and solver execution remain separate gated work.
