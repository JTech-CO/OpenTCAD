# M2 output, cancellation, and redaction foundation

[한국어](../../ko/m2/output-cancellation-redaction.md) | [M2 status](README.md)

- Status: `gated-active`, mock only
- Work items: BRK-004 extension, BRK-007, BRK-008 foundation
- Product runtime access: not granted

This slice strengthens the internal broker contract without adding a service, runtime socket, subprocess, solver, host extraction, or Docker and Podman product adapter.

## Canonical output archive

Successful mock execution returns an untrusted `RawArtifactArchive`, not a trusted list of records. The broker validates the actual bytes against the approved output names and the runtime-reported `ArtifactRecord` values before creating `ValidatedArtifactArchive`.

The output archive uses the same deterministic, uncompressed USTAR metadata as the input archive. Validation is memory-only and rejects alternate metadata, compression, traversal, separators, Unicode names, links, devices, directories, FIFO entries, sparse entries, case-fold collisions, count or size overflow, hash substitution, missing or extra members, and trailing bytes. Empty regular output files are allowed and still receive an exact SHA-256 record.

## Cancellation identity

`JobIdentity` is derived only from the canonical server job UUID. It fixes:

- label: `tcad.job_id=<job UUID>`;
- object name: `opentcad-job-<job UUID>`;
- managed volume name: `opentcad-job-<job UUID>-data`.

SUPREM, remesh, and DEVSIM use the same derivation. Kind, caller text, runtime-native ID, host path, and raw object name cannot alter cancellation ownership.

`SandboxBroker.cancel()` queries by the exact job UUID, rejects cross-job handles and ambiguous object sets, sends `TerminationReason.CANCELLATION`, requires a cancelled terminal classification, removes the container before the volume, and re-queries for zero managed objects.

## Structured public records and internal diagnostics

Public broker errors contain only stable code, phase, retry disposition, and a normalized backend ID. Public events contain sequence, state, phase, and stable code. Archive bytes, raw backend values, locale-dependent messages, secrets, and host paths are absent from repr and public dictionaries.

`InternalDiagnostic` retains raw backend detail only for a trusted in-process diagnostic sink. Its repr also hides raw fields. This is not durable logging and grants no external diagnostic endpoint.

## Verified controls

The dependency-free suite now contains 77 tests. In addition to the output, identity, and redaction controls above, it exercises all eleven execution cancellation checkpoints, wrong-identity and malformed signals, concurrent cleanup serialization, already-absent convergence, durable-state revision CAS, event idempotency, transition safety, recovery scanning, and persisted-shape redaction. See the [lifecycle cancellation, cleanup, and state contract](lifecycle-cleanup-state.md).

## Remaining boundary

There is still no product runtime adapter, broker service transport, runtime detection, worker integration, live broker-to-store wiring, restart-safe cancellation, cross-process cancellation arbitration, solver execution, or runtime socket access. Phase-addressable mock injection and process-local cleanup idempotence are implemented; an inactive SQLite candidate now covers durable events and process hard-exit recovery while product activation remains gated.
