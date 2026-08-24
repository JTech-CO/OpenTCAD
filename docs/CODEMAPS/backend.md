# Backend code map / 백엔드 코드맵

## English

The current backend is an engine-independent M2 runtime and mock broker foundation. It has no web service, worker integration, broker service transport, product Docker or Podman adapter, runtime detection, socket access, database, or solver invocation.

| Path | Responsibility |
|---|---|
| `backend/app/runtime/models.py` | Immutable boundary models, capability vocabulary, result classifications, opaque handles |
| `backend/app/runtime/errors.py` | Stable locale-independent error, phase, and retry records |
| `backend/app/runtime/policy.py` | Approved profile validation and fail-closed capability checks |
| `backend/app/runtime/protocol.py` | Runtime-neutral async lifecycle protocol |
| `backend/app/runtime/mock_backend.py` | Strict stateful in-memory contract test double with no host interaction |
| `backend/app/broker/archive.py` | Canonical in-memory input USTAR builder and traversal, link, device, compression, collision, and bomb defense |
| `backend/app/broker/output_archive.py` | Untrusted output USTAR builder, byte/manifest validator, and artifact substitution defense |
| `backend/app/broker/cancellation.py` | Typed fixed-identity cancellation request and redacted outcome |
| `backend/app/broker/diagnostics.py` | Repr-hidden internal raw diagnostics separated from public errors |
| `backend/app/broker/orchestrator.py` | Mock-only typed execution, cancellation, redacted outcome, exact cleanup, and reconciliation |
| `backend/tests/runtime/` | Policy, identity, lifecycle, fault mapping, and cleanup contract tests |
| `backend/tests/broker/` | Input/output archive attacks, cancellation, redaction, state-machine, negative cleanup, and reconciliation tests |
| `validation/manifests/m2-runtime-foundation.json` | Machine-readable gate state and frozen source evidence |
| `tools/check-m2.mjs` | Drift, gate, scope, and hash verifier |

The allowed dependency direction is `domain worker -> SandboxSpec -> SandboxPolicy -> ValidatedSandboxSpec and JobIdentity -> RuntimeBackend`. A future runtime adapter belongs behind the protocol. A future reviewed broker service is the only component allowed to own runtime access, after entry and security gates are approved.

## 한국어

현재 백엔드는 엔진 독립 M2 runtime 및 mock broker 기반입니다. 웹 서비스, 워커 통합, broker service transport, 제품 Docker 또는 Podman 어댑터, 런타임 탐지, 소켓 접근, 데이터베이스, 솔버 호출은 없습니다.

| 경로 | 책임 |
|---|---|
| `backend/app/runtime/models.py` | 불변 경계 모델, capability 어휘, 결과 classification, opaque handle |
| `backend/app/runtime/errors.py` | 언어와 무관한 stable error, phase, retry record |
| `backend/app/runtime/policy.py` | 승인 profile 검증과 실패 폐쇄 capability 검사 |
| `backend/app/runtime/protocol.py` | 런타임 중립 비동기 lifecycle protocol |
| `backend/app/runtime/mock_backend.py` | 호스트와 상호 작용하지 않는 엄격한 stateful memory 기반 test double |
| `backend/app/broker/archive.py` | Canonical memory 기반 input USTAR builder와 traversal, link, device, 압축, collision, bomb 방어 |
| `backend/app/broker/output_archive.py` | 신뢰되지 않은 output USTAR builder, byte/manifest validator, artifact substitution 방어 |
| `backend/app/broker/cancellation.py` | Typed 고정 identity cancellation request와 redacted outcome |
| `backend/app/broker/diagnostics.py` | 공개 error와 분리하고 repr에서 숨긴 내부 raw diagnostic |
| `backend/app/broker/orchestrator.py` | Mock 전용 typed execution, cancellation, redacted outcome, 정확한 cleanup, reconciliation |
| `backend/tests/runtime/` | 정책, identity, lifecycle, 장애 mapping, 정리 계약 test |
| `backend/tests/broker/` | Input/output archive 공격, cancellation, redaction, state machine, negative cleanup, reconciliation test |
| `validation/manifests/m2-runtime-foundation.json` | 기계 판독 게이트 상태와 고정 source 증거 |
| `tools/check-m2.mjs` | drift, gate, 범위, hash 검증기 |

허용된 의존 방향은 `domain worker -> SandboxSpec -> SandboxPolicy -> ValidatedSandboxSpec 및 JobIdentity -> RuntimeBackend`입니다. 향후 런타임 adapter는 protocol 뒤에 있어야 합니다. 향후 검토된 broker service는 진입 및 보안 게이트 승인 후 런타임 접근을 소유할 수 있는 유일한 구성 요소입니다.
