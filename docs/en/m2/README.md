# M2 runtime contract foundation

[한국어](../../ko/m2/README.md)

M2 is `gated-active`. The runtime-neutral model, stable errors, fail-closed policy validator, protocol, and in-memory mock backend are implemented for contract review. No Docker or Podman product adapter, sandbox broker service, runtime detection, worker integration, or runtime socket access exists.

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
| RUN-007 contract suite | Mock only | Fifteen tests include a 20-case lifecycle loop with zero managed objects |
| M2 exit | Not met | No real adapter, broker, solver corpus, or native platform qualification |

## Implemented boundary

The future worker can construct only a `SandboxSpec` containing a server UUID, approved profile ID, job kind, immutable image identity, fixed input manifest, bounded limits, approved environment profile, and expected output names. The model has no field for a command, shell, entrypoint, host path, mount, network mode, user, capability, security option, device, or runtime socket.

Only `SandboxPolicy.validate()` can create `ValidatedSandboxSpec`. A backend receives that validated type, opaque volume and container handles, and stable termination reasons. Unsupported mandatory capabilities are reported as `capability-missing`; the policy never drops an option and continues.

The mock backend invokes no process and owns no socket. It exists to make lifecycle and error semantics reusable before Docker and Podman implementations are authorized.

## Artifacts

- [RuntimeBackend ADR](runtime-backend-adr.md)
- [Sandbox broker threat model](broker-threat-model.md)
- [`RuntimeBackend` protocol](../../../backend/app/runtime/protocol.py)
- [Runtime models](../../../backend/app/runtime/models.py)
- [Fail-closed policy](../../../backend/app/runtime/policy.py)
- [Stable errors](../../../backend/app/runtime/errors.py)
- [Mock backend](../../../backend/app/runtime/mock_backend.py)
- [Policy tests](../../../backend/tests/runtime/test_policy.py)
- [Lifecycle contract tests](../../../backend/tests/runtime/test_mock_backend.py)

Run the foundation with:

```sh
npm run check:m2
npm run test:runtime
```

Python 3.12 through 3.14 is supported for this dependency-free contract suite. CI pins Python 3.12.

## Next gate

Review and approve the ADR and threat model only after the unresolved M1 entry evidence is addressed. The next implementation slice is archive validation and broker orchestration around the mock contract. Real Docker and Podman adapters remain blocked until an approved immutable engine profile and the applicable M2 entry gates exist.
