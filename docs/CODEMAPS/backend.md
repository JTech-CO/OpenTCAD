# Backend code map / 백엔드 코드맵

## English

The current backend is an engine-independent M2 contract foundation. It has no web service, worker integration, sandbox broker, product Docker or Podman adapter, runtime detection, socket access, database, or solver invocation.

| Path | Responsibility |
|---|---|
| `backend/app/runtime/models.py` | Immutable boundary models, capability vocabulary, result classifications, opaque handles |
| `backend/app/runtime/errors.py` | Stable locale-independent error, phase, and retry records |
| `backend/app/runtime/policy.py` | Approved profile validation and fail-closed capability checks |
| `backend/app/runtime/protocol.py` | Runtime-neutral async lifecycle protocol |
| `backend/app/runtime/mock_backend.py` | Strict stateful in-memory contract test double with no host interaction |
| `backend/tests/runtime/` | Policy, lifecycle, fault mapping, and cleanup contract tests |
| `validation/manifests/m2-runtime-foundation.json` | Machine-readable gate state and frozen source evidence |
| `tools/check-m2.mjs` | Drift, gate, scope, and hash verifier |

The allowed dependency direction is `domain worker -> SandboxSpec -> SandboxPolicy -> ValidatedSandboxSpec -> RuntimeBackend`. A future runtime adapter belongs behind the protocol. A future broker is the only component allowed to own runtime access, after entry and security gates are approved.

## 한국어

현재 백엔드는 엔진 독립 M2 계약 기반입니다. 웹 서비스, 워커 통합, 샌드박스 브로커, 제품 Docker 또는 Podman 어댑터, 런타임 탐지, 소켓 접근, 데이터베이스, 솔버 호출은 없습니다.

| 경로 | 책임 |
|---|---|
| `backend/app/runtime/models.py` | 불변 경계 모델, capability 어휘, 결과 classification, opaque handle |
| `backend/app/runtime/errors.py` | 언어와 무관한 stable error, phase, retry record |
| `backend/app/runtime/policy.py` | 승인 profile 검증과 실패 폐쇄 capability 검사 |
| `backend/app/runtime/protocol.py` | 런타임 중립 비동기 lifecycle protocol |
| `backend/app/runtime/mock_backend.py` | 호스트와 상호 작용하지 않는 엄격한 stateful memory 기반 test double |
| `backend/tests/runtime/` | 정책, lifecycle, 장애 mapping, 정리 계약 테스트 |
| `validation/manifests/m2-runtime-foundation.json` | 기계 판독 게이트 상태와 고정 source 증거 |
| `tools/check-m2.mjs` | drift, gate, 범위, hash 검증기 |

허용된 의존 방향은 `domain worker -> SandboxSpec -> SandboxPolicy -> ValidatedSandboxSpec -> RuntimeBackend`입니다. 향후 런타임 adapter는 protocol 뒤에 있어야 합니다. 향후 브로커는 진입 및 보안 게이트 승인 후 런타임 접근을 소유할 수 있는 유일한 구성 요소입니다.
