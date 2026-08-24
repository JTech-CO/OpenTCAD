# M2 runtime contract 기반

[English](../../en/m2/README.md)

M2는 `gated-active` 상태입니다. 계약 검토를 위해 runtime-neutral model, stable error, fail-closed policy validator, protocol, memory 기반 mock backend를 구현했습니다. Docker 또는 Podman 제품 adapter, sandbox broker service, runtime detection, worker integration, runtime socket 접근은 없습니다.

M1 corpus가 green이 아니고 runtime ADR은 승인 전 제안 상태이며 broker threat model도 승인 전 초안이므로 M2 진입 조건은 미충족입니다.

## 작업 현황

| 항목 | 상태 | 현재 증거 |
|---|---|---|
| RUN-001 runtime 특성 관찰 | 관찰 완료, 비승격 | Docker Desktop과 WSL2 rootless Podman이 비솔버 OCI 장애 행렬을 통과함 |
| RUN-002 `RuntimeBackend` contract | 기반 test 완료 | Typed async lifecycle, capability model, stable error, strict mock backend |
| RUN-003 공통 sandbox policy | 기반 test 완료 | Capability 누락, mutable image identity, profile 차이, limit 초과를 fail closed 처리 |
| RUN-004 Podman adapter | 차단 | 진입 게이트와 승인된 engine profile이 없음 |
| RUN-005 Docker adapter | 차단 | 진입 게이트와 승인된 engine profile이 없음 |
| RUN-006 runtime detection | 시작 전 | 결정론적 우선순위와 명시 override는 ADR 후속 작업 |
| RUN-007 contract suite | Mock만 완료 | Test 15개에 관리 객체 0개로 끝나는 20회 lifecycle 반복 포함 |
| M2 종료 | 미충족 | 실제 adapter, broker, solver corpus, native platform 검증이 없음 |

## 구현된 경계

향후 worker는 server UUID, 승인 profile ID, job kind, 불변 image identity, 고정 input manifest, 제한된 resource limit, 승인 environment profile, 예상 output 이름만 포함한 `SandboxSpec`을 만들 수 있습니다. Model에는 command, shell, entrypoint, host path, mount, network mode, user, capability, security option, device, runtime socket 필드가 없습니다.

`SandboxPolicy.validate()`만 `ValidatedSandboxSpec`을 만들 수 있습니다. Backend는 이 검증 타입, opaque volume 및 container handle, stable 종료 사유만 받습니다. 필수 capability를 지원하지 않으면 `capability-missing`으로 거부하며 option을 제거하고 실행하지 않습니다.

Mock backend는 process를 실행하지 않고 socket도 소유하지 않습니다. Docker와 Podman 구현이 허용되기 전에 lifecycle과 error 의미를 재사용 가능하게 고정하는 용도입니다.

## 산출물

- [RuntimeBackend ADR](runtime-backend-adr.md)
- [Sandbox broker threat model](broker-threat-model.md)
- [`RuntimeBackend` protocol](../../../backend/app/runtime/protocol.py)
- [Runtime model](../../../backend/app/runtime/models.py)
- [Fail-closed policy](../../../backend/app/runtime/policy.py)
- [Stable error](../../../backend/app/runtime/errors.py)
- [Mock backend](../../../backend/app/runtime/mock_backend.py)
- [Policy test](../../../backend/tests/runtime/test_policy.py)
- [Lifecycle contract test](../../../backend/tests/runtime/test_mock_backend.py)

다음 명령으로 기반을 검사합니다.

```sh
npm run check:m2
npm run test:runtime
```

의존성이 없는 이 contract suite는 Python 3.12부터 3.14까지 지원합니다. CI는 Python 3.12를 고정합니다.

## 다음 게이트

해결되지 않은 M1 진입 증거를 처리한 뒤 ADR과 threat model을 검토하고 승인해야 합니다. 다음 구현 범위는 mock contract 주변의 archive 검증과 broker orchestration입니다. 승인된 불변 engine profile과 해당 M2 진입 게이트가 생길 때까지 실제 Docker 및 Podman adapter는 차단합니다.
