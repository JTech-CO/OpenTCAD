# M0 OCI fault matrix observation

[한국어](../../ko/m0/oci-fault-matrix.md) | [M0 status](README.md)

## Result

OpenTCAD observed the reviewed non-solver fault matrix on Windows Docker Desktop and WSL2 Debian rootless Podman. Both runtimes passed six named scenarios and a 20-case mixed success, failure, and cancellation loop. Every managed container was removed by exact name, the observation label was queried after every case, and both final orphan counts were zero.

This is a non-promoting runtime characterization. It does not qualify a solver, product runtime adapter, operating system, or release image.

| Runtime | Profile observed | Named scenarios | Mixed loop | Final labelled containers |
|---|---|---:|---:|---:|
| Docker Desktop 29.6.2 | Linux amd64, cgroup v2, Docker-managed WSL2 VM | 6/6 | 20/20 | 0 |
| Podman 5.4.2 | Linux amd64, rootless, cgroup v2, WSL2 Debian | 6/6 | 20/20 | 0 |

The sanitized facts and evidence hashes are in [`OCI_FAULT_MATRIX_OBSERVATION.json`](../../../m0/OCI_FAULT_MATRIX_OBSERVATION.json). Raw output, inspect records, command metadata, and external manifests are not committed.

## Reviewed execution boundary

The collector accepts only [`m0-oci-fault-matrix.json`](../../../validation/plans/m0-oci-fault-matrix.json). The plan pins a locally present Debian image by OCI index digest and uses `pull=never`. It contains no SUPREM-IV.GS, Gmsh, DEVSIM, or OpenTCAD solver payload.

Each container was created with:

- network disabled;
- all capabilities dropped and `no-new-privileges` enabled;
- a read-only root filesystem with no writable temporary filesystems;
- UID and GID `65534:65534`;
- no mounts, no restart, and explicit PID, memory, CPU, stop-time, wall-time, and output limits.

Commands are fixed argument arrays from a small allowlist and never pass through a shell. Before the first case, the collector rejects any pre-existing container carrying its runtime-specific observation label. Once a container is created, cleanup addresses only that exact generated name.

## Named fault results

| Scenario | Expected and observed result | Additional assertion |
|---|---|---|
| Process policy | Exit 0 | Effective capabilities were zero, `NoNewPrivs` was 1, and all process UIDs were 65534 |
| Read-only root | Exit 1 | A write under `/tmp` was rejected on both runtimes |
| Declared nonzero exit | Exit 1 | A normal container failure stayed distinct from a supervisor fault |
| Timeout | `timed-out` | The command worker reset before the first cleanup inspection |
| Cancellation | `cancelled` | The command worker reset before the first cleanup inspection |
| Output bomb | `output-limit-exceeded` | Combined capture stopped at 32 KiB, output was truncated, and the worker reset |

The mixed loop repeated success, nonzero exit, and cancellation in a fixed pattern: 7 successful cases, 7 nonzero exits, and 6 cancellations. All 20 cases passed policy, outcome, exact-removal, absence, and zero-orphan checks.

## Cross-runtime finding

The first rootless Podman attempt exposed a real default difference. Podman can make temporary directories writable even when the root filesystem is read-only. The reviewed contract therefore declares `writableTemporaryFilesystems: false`, and the Podman mapping adds `--read-only-tmpfs=false`. Docker needs no extra flag for the same observed `/tmp` behavior. The failed diagnostic attempt also removed its exact container and ended with zero labelled containers; it is not part of the final record.

This backend-specific mapping belongs in the future runtime capability contract. Treating `--read-only` as identical across runtimes would be unsafe.

## Re-run the non-promoting collector

Use a new absolute directory outside the repository. The reviewed image must already exist locally; the collector will not pull it.

```sh
node tools/observe-oci-fault-matrix.mjs \
  --plan validation/plans/m0-oci-fault-matrix.json \
  --runtime docker \
  --output <absolute-external-output-directory>
```

On Windows with Podman in WSL:

```powershell
node tools/observe-oci-fault-matrix.mjs `
  --plan validation/plans/m0-oci-fault-matrix.json `
  --runtime podman `
  --wsl-distribution Debian `
  --output <absolute-external-output-directory>
```

The output directory must not exist. The collector writes raw evidence only there, exits nonzero on any drift, and never promotes a baseline.

## Remaining gates

- Implement the M2 `RuntimeBackend` contract and product Docker and Podman adapters.
- Repeat the matrix through the API, worker, broker, managed job volume, and durable job-state path.
- Inject worker, broker, runtime, and host crashes in addition to command faults.
- Repeat with authorized solver fixtures and approved immutable engine images.
- Qualify native Linux, Windows, macOS, and Podman Machine separately.

M0 remains open because rights, clean solver logs, SBOM license review, numerical corpus, portability, and release approval are still incomplete.
