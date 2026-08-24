# M0 fault-path contract foundation

[한국어](../../ko/m0/fault-path-foundation.md) | [M0 status](README.md)

This foundation tests process-supervision behavior without a solver or container runtime. It does not qualify Docker, Podman, SUPREM-IV.GS, Gmsh, DEVSIM, or a product worker.

## Implemented controls

[`FaultPathSupervisor`](../../../validation/faults/supervisor.mjs) owns one persistent command worker and accepts one active job at a time. Commands use argument arrays with `shell: false`, inherit only an allowlisted environment, and receive explicit timeout and combined stdout/stderr limits.

| Trigger | Stable classification | Containment action | Recovery assertion |
|---|---|---|---|
| Deadline expires | `timed-out` | Terminate the active process, escalate after a bounded grace period, reset the worker | The next job runs in a new generation and succeeds |
| `AbortSignal` fires | `cancelled` | Terminate the active process and reset the worker | The next job runs under a different worker PID |
| Combined output exceeds the byte cap | `output-limit-exceeded` | Keep no more than the declared cap, terminate the process, reset the worker | Captured bytes equal the cap and the next job succeeds |
| Worker exits without a result | `worker-crashed` | Reject the job and discard the worker | A later job must start a new generation |

Healthy jobs reuse the same worker generation. `nonzero-exit` remains a failed job classification, but a completed child process does not force a supervisor reset. Spawn and protocol failures do force a reset.

On POSIX hosts the command runs in a separate process group so termination targets that group. Windows uses the direct child-process signal path in this foundation. The validation-only OCI collector now adds container identity, kill, remove, and orphan queries; product adapters still need to implement that contract before support can be claimed.

## Fault injection evidence

[`supervisor.test.mjs`](../../../validation/faults/supervisor.test.mjs) launches real Node child processes rather than mocking the process boundary. It verifies:

1. healthy worker reuse;
2. timeout classification followed by a fresh worker and successful job;
3. cancellation classification followed by a fresh worker and successful job;
4. combined output truncation at the exact cap followed by recovery;
5. rejection of invalid limits and concurrent jobs.

Run the complete engine-independent suite with:

```sh
npm run test:validation
```

The machine-readable status is [`m0-fault-path-foundation.json`](../../../validation/manifests/m0-fault-path-foundation.json). Its `baselinePromotionAllowed`, solver evidence, and container-runtime evidence remain `false` because that record describes only the engine-independent suite.

## Non-solver OCI extension

The separate [OCI fault matrix observation](oci-fault-matrix.md) ran the same terminal classifications through Docker Desktop and WSL2 rootless Podman. Both runtimes passed six named cases and 20 mixed-loop cases, replaced the command worker after injected faults, removed every container by exact name, and ended with zero labelled containers. The pinned Debian image contains no solver, and the collector is validation tooling rather than a product adapter.

## Remaining runtime evidence

- Repeat the matrix through product Docker and Podman adapters, the broker, and durable job state.
- Exercise cancellation during real SUPREM, remesh, and DEVSIM work using authorized inputs and images.
- Inject worker, broker, runtime, and host crashes and verify durable job-state repair.
- Qualify the same behavior on native Windows, macOS, and Linux.

The foundation and OCI observation close only engine-independent supervision and non-solver runtime characterization slices. They do not close BASE-001 or the M0 exit gate.
