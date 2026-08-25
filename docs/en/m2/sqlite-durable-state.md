# M2 SQLite durable-state candidate

[한국어](../../ko/m2/sqlite-durable-state.md) | [M2 status](README.md)

- Status: candidate adapter and recovery contract tested, not product-enabled
- Work items: RUN-007 and BRK-006 extension
- Runtime, solver, and service authority: unchanged and disabled
- Inactive phase-time composition: mock execution contract tested

## Decision

`SQLiteJobStateStore` is the first file-backed candidate for the existing `DurableJobStateStore` boundary. SQLite is available through the Python standard library on Windows, macOS, and Linux and fits the single-machine local-server target. This decision does not select a multi-host queue. An explicit mock-only composition can open the candidate for contract tests, but direct broker execution and every product path remain disabled.

The constructor accepts only a local file path. It rejects the in-memory database and SQLite URI forms. The database location is an administrator-owned internal setting, not a project archive field, request field, host mount, or sandbox input.

## Transaction and schema contract

Schema version 1 is an append-only `job_events` table. Each row contains the redacted durable event fields plus its committed revision. The database enforces unique event IDs, unique job-operation-sequence slots, and unique job revisions. No raw diagnostic, payload, command, secret, runtime-native identifier, or host path is stored.

Each append uses `BEGIN IMMEDIATE`, checks an identical event replay before revision CAS, validates the shared transition table, inserts one new revision, and commits. Concurrent writers therefore serialize at the database boundary and only one writer can satisfy a given expected revision. WAL mode and `synchronous=FULL` are required. SQLite and filesystem messages are translated to the stable `store-unavailable` code and are not exposed through public exceptions.

`PRAGMA user_version` is the forward-only migration marker:

1. A new version 0 database is created as the exact version 1 schema in one transaction.
2. An exact version 1 database is accepted.
3. An unknown newer version or a mismatched table definition fails closed.
4. No destructive, downgrade, or best-effort migration runs automatically.

## Common conformance and hard-exit proof

The SQLite candidate runs the unchanged six-case adapter conformance suite. It proves empty reads, committed visibility through a fresh adapter handle, idempotent replay, event and operation-slot conflicts, concurrent CAS, and bounded recovery pagination.

A separate Python process opens the file, lets `CrashRecoveryCoordinator` commit a `cleaning` claim, and calls `os._exit(91)` at the `after-claim` checkpoint. A fresh parent-process adapter observes that committed revision. Replaying the same recovery request reuses the deterministic claim event, reconciles the exact job, and closes the job as `failed:stale-state` without synthesizing success.

This is process hard-exit evidence. It is not a claim of host power-loss tolerance, filesystem-corruption recovery, backup and restore correctness, multi-process lease ownership, or multi-host operation.

## Retention and recovery policy

Version 1 performs no automatic deletion or compaction. Removing old rows would discard event-ID and operation-slot idempotency evidence as well as the audit sequence. A future retention design must preserve the latest snapshot, event-ID tombstones, operation-slot tombstones, revision monotonicity, backup and restore behavior, and recovery scan semantics before deletion can be enabled.

The database remains a candidate test artifact. An explicit mock-only composition writes execution and external-cancellation phase events to it after startup recovery, but direct broker calls and services do not open it. No product runtime or solver operation depends on it.

## Next gate

The next state slice is durable operation ownership and fencing across execution, cancellation, and recovery. Distributed coordination, backup and restore, power-loss qualification, product Docker and Podman adapters, runtime sockets, and solver execution remain separate gated work.
