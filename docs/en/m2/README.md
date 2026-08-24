# M2 runtime contract foundation

[한국어](../../ko/m2/README.md)

M2 is `gated-active`. The runtime-neutral model, stable errors, fail-closed policy validator, protocol, canonical input-archive validator, strict mock backend, and internal mock broker orchestrator are implemented for contract review. No Docker or Podman product adapter, sandbox broker service transport, runtime detection, worker integration, or runtime socket access exists.

M2 entry is not met because the M1 corpus is not green, the runtime ADR is proposed rather than approved, and the broker threat model is a draft rather than approved.

## Workboard

| Item | Status | Current evidence |
|---|---|---|
| RUN-001 runtime characterization | Observed, non-promoting | Docker Desktop and WSL2 rootless Podman passed the non-solver OCI fault matrix |
| RUN-002 `RuntimeBackend` contract | Foundation tested | Typed async lifecycle, capability model, stable errors, and strict mock backend |
| RUN-003 common sandbox policy | Foundation tested | Missing capabilities, mutable image identity, profile drift, and excessive limits fail closed |
| RUN-004 Podman adapter | Blocked | Entry gates and approved engine profile are missing |
| RUN-005 Docker adapter | Blocked | Entry gates and approved engine profile are missing |
| RUN-006 runtime detection | Not started | Deterministic precedence and explicit override remain an ADR follow-up |
| RUN-007 contract suite | Mock broker tested | Twenty-nine tests include archive attacks, two 20-case loops, reconciliation, and cleanup negative control |
| BRK-001 typed broker protocol | Foundation tested | Internal library accepts typed spec plus canonical bytes and returns redacted records |
| BRK-003 managed volume lifecycle | Mock tested | Create, stage, run, collect, container removal, volume removal, and zero-object query |
| BRK-004 archive defense | Foundation tested | Traversal, links, devices, compression, metadata, collisions, bombs, and drift fail closed |
| BRK-006 reconciliation | Mock tested | Pre-existing running objects are killed and removed; residual objects become `cleanup-failed` |
| M2 exit | Not met | No real adapter, broker service, solver corpus, durable state, or native platform qualification |

## Implemented boundary

The future worker can construct only a `SandboxSpec` containing a server UUID, approved profile ID, job kind, immutable image identity, fixed input manifest, bounded limits, approved environment profile, and expected output names. The model has no field for a command, shell, entrypoint, host path, mount, network mode, user, capability, security option, device, or runtime socket.

Only `SandboxPolicy.validate()` can create `ValidatedSandboxSpec`. A backend receives that validated type, opaque volume and container handles, and stable termination reasons. Unsupported mandatory capabilities are reported as `capability-missing`; the policy never drops an option and continues.

The mock backend invokes no process and owns no socket. The internal broker library validates an exact uncompressed USTAR stream in memory, accepts only `ValidatedInputArchive` at the staging boundary, removes containers before volumes, and re-queries managed objects before reporting cleanup success. It exposes no service transport and exists only to make lifecycle, archive, cleanup, and error semantics reusable before Docker and Podman implementations are authorized.

## Artifacts

- [RuntimeBackend ADR](runtime-backend-adr.md)
- [Sandbox broker threat model](broker-threat-model.md)
- [Broker and canonical archive foundation](broker-archive-foundation.md)
- [`RuntimeBackend` protocol](../../../backend/app/runtime/protocol.py)
- [Runtime models](../../../backend/app/runtime/models.py)
- [Fail-closed policy](../../../backend/app/runtime/policy.py)
- [Stable errors](../../../backend/app/runtime/errors.py)
- [Mock backend](../../../backend/app/runtime/mock_backend.py)
- [Policy tests](../../../backend/tests/runtime/test_policy.py)
- [Lifecycle contract tests](../../../backend/tests/runtime/test_mock_backend.py)
- [Canonical archive validator](../../../backend/app/broker/archive.py)
- [Mock broker orchestrator](../../../backend/app/broker/orchestrator.py)
- [Archive defense tests](../../../backend/tests/broker/test_archive.py)
- [Broker cleanup tests](../../../backend/tests/broker/test_orchestrator.py)

Run the foundation with:

```sh
npm run check:m2
npm run test:runtime
```

Python 3.12 through 3.14 is supported for this dependency-free contract suite. CI pins Python 3.12.

## Next gate

Review and approve the ADR and threat model only after the unresolved M1 entry evidence is addressed. The next gated slice is output-archive validation, cancellation identity, and structured event-redaction fault tests around the mock broker. Real Docker and Podman adapters remain blocked until an approved immutable engine profile and the applicable M2 entry gates exist.
