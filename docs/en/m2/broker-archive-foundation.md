# M2 broker and canonical archive foundation

[한국어](../../ko/m2/broker-archive-foundation.md) | [M2 status](README.md)

- Status: `gated-active`, mock only
- Work items: BRK-001, BRK-003, BRK-004, BRK-006 foundation
- Product runtime access: not granted

This slice adds an internal Python library for broker contract tests. It exposes no HTTP, IPC, or socket service, invokes no subprocess, touches no runtime, writes no archive member to the host filesystem, and cannot execute a solver. A running Docker installation does not change those boundaries.

## Canonical input archive

The API-to-broker transfer is one deterministic, uncompressed USTAR byte stream. The builder and the broker-side validator both require:

- an exact ordered `InputFile` manifest with SHA-256 and byte length;
- flat ASCII names of at most 100 USTAR bytes;
- no absolute path, separator, parent path, case-fold collision, or duplicate;
- regular files only, with fixed mode `0400`, UID/GID `65534`, time `0`, and empty owner names;
- exact file-count, total-content, and archive-stream ceilings;
- no gzip or other compression, PAX metadata, sparse file, symlink, hardlink, directory, FIFO, or device;
- an exact byte-for-byte rebuild of the canonical archive, which rejects alternate headers and trailing data.

Validation uses memory only. `tarfile.extract()` and `extractall()` are never called. A successful validator creates `ValidatedInputArchive`, and only this policy-only type may cross `RuntimeBackend.stage_inputs`.

## Mock broker state machine

`SandboxBroker.execute()` performs the following contract sequence:

1. Probe the backend and reject unavailable or degraded health.
2. Apply `SandboxPolicy` and validate the canonical archive before creating a runtime object.
3. Ensure the approved image, create one managed volume, stage the validated archive, create and start one container, and wait.
4. Collect an untrusted output archive only for a successful terminal result and require exact canonical bytes plus manifest agreement.
5. Kill a still-running container when required, remove the container before the volume, and query the job identity again.
6. Return only stable, redacted error, phase, retry, state, result, artifact, and cleanup records.

`reconcile()` removes pre-existing managed objects for one job identity. It first attempts exact container removal, kills a running container when state requires it, then removes volumes and reports the remaining counts.

## Verified controls

The dependency-free suite includes input and output malicious-name, link, device, compression, metadata, trailing-byte, count, size, hash, substitution, and case-collision controls. Broker tests cover success, capability downgrade, invalid archive before allocation, wait failure, missing artifact, stale running-job reconciliation, a 20-case mixed loop, and a deliberately leaky backend. The leaky negative control proves that residual managed objects cannot be reported as successful cleanup.

## Remaining boundary

The companion [output, cancellation, and redaction foundation](output-cancellation-redaction.md) validates artifact bytes and fixes cancellation identity and public diagnostics. A later [SQLite durable-state candidate](sqlite-durable-state.md) now proves file-backed state and process hard-exit recovery without enabling the product. There is still no Docker or Podman product adapter, broker service transport, runtime detection, worker integration, or live state wiring. Real runtime work remains blocked by the M2 entry conditions and an approved immutable engine profile.
