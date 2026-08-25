# Backend code map / 백엔드 코드맵

## English

The current backend is an engine-independent M2 runtime and mock broker foundation. It includes an inactive file-backed SQLite durable-state candidate and an explicit mock-only phase-time composition with startup recovery admission and durable external-cancellation arbitration. It has no external cancellation transport, web service, worker integration, broker service transport, product Docker or Podman adapter, runtime detection, socket access, or solver invocation.

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
| `backend/app/broker/cancellation_arbitration.py` | Five deterministic durable-cancellation interruption seams and test-only crash signal |
| `backend/app/broker/lifecycle.py` | Eleven deterministic cancellation checkpoints and the in-process signal contract |
| `backend/app/broker/cleanup.py` | Injectable process-local job cleanup coordinator |
| `backend/app/broker/state.py` | Durable state protocol, shared revision/transition and operation-slot rules, and non-durable shared-backing test double |
| `backend/app/broker/sqlite_state.py` | Inactive file-backed SQLite candidate, schema v1, transactional CAS, redacted failures, and bounded recovery scan |
| `backend/app/broker/state_mapping.py` | Deterministic redacted outcome mapping and CAS batch recorder |
| `backend/app/broker/live_state.py` | Phase-time deterministic durable emissions and fail-safe write-session contract |
| `backend/app/broker/recovery.py` | Bounded CAS claim, exact-job reconciliation, and mock crash/restart convergence |
| `backend/app/broker/state_composition.py` | Mock-only startup recovery gate, opt-in durable execution, and external-cancellation CAS admission |
| `backend/app/broker/diagnostics.py` | Repr-hidden internal raw diagnostics separated from public errors |
| `backend/app/broker/orchestrator.py` | Mock-only typed execution, phase and durable cancellation, redacted outcomes, idempotent cleanup, and reconciliation |
| `backend/tests/runtime/` | Policy, identity, lifecycle, fault mapping, and cleanup contract tests |
| `backend/tests/broker/` | Archive attacks, phase and durable cancellation, redaction, cleanup concurrency, event mapping, common adapter conformance, live-state composition, CAS arbitration, reconciliation, and crash/restart contract tests |
| `validation/manifests/m2-runtime-foundation.json` | Machine-readable gate state and frozen source evidence |
| `tools/check-m2.mjs` | Drift, gate, scope, and hash verifier |

The allowed execution dependency direction is `domain worker -> SandboxSpec -> SandboxPolicy -> ValidatedSandboxSpec and JobIdentity -> RuntimeBackend`. Durable state remains a side boundary through `DurableJobStateStore`, not part of `RuntimeBackend`; outcome mapping, SQLite persistence, mock-only live composition, and recovery depend on that boundary without granting product runtime access. A future runtime adapter belongs behind the runtime protocol. A future reviewed broker service is the only component allowed to own runtime access, after entry and security gates are approved.

## 한국어

현재 백엔드는 엔진 독립 M2 runtime 및 mock broker 기반입니다. 비활성 file-backed SQLite durable-state 후보와 startup recovery admission 및 durable external cancellation 중재를 갖춘 명시적인 mock 전용 phase-time composition을 포함합니다. 외부 cancellation transport, 웹 service, worker 통합, broker service transport, 제품 Docker 또는 Podman adapter, runtime detection, socket 접근, solver 호출은 없습니다.

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
| `backend/app/broker/cancellation_arbitration.py` | 결정론적 durable cancellation 중단 경계 5곳과 test 전용 crash signal |
| `backend/app/broker/lifecycle.py` | 결정론적 cancellation checkpoint 11곳과 in-process signal 계약 |
| `backend/app/broker/cleanup.py` | 주입 가능한 process-local job cleanup coordinator |
| `backend/app/broker/state.py` | Durable state protocol, 공통 revision, transition 및 operation slot 규칙, non-durable shared-backing test double |
| `backend/app/broker/sqlite_state.py` | 비활성 file-backed SQLite 후보, schema v1, transactional CAS, redacted failure, bounded recovery scan |
| `backend/app/broker/state_mapping.py` | 결정론적 redacted outcome mapping 및 CAS batch recorder |
| `backend/app/broker/live_state.py` | Phase-time 결정론적 durable emission 및 fail-safe write session 계약 |
| `backend/app/broker/recovery.py` | Bounded CAS claim, 정확한 job reconciliation, mock crash/restart 수렴 |
| `backend/app/broker/state_composition.py` | Mock 전용 startup recovery gate, opt-in durable execution, 외부 cancellation CAS admission |
| `backend/app/broker/diagnostics.py` | 공개 error와 분리하고 repr에서 숨긴 내부 raw diagnostic |
| `backend/app/broker/orchestrator.py` | Mock 전용 typed execution, phase 및 durable cancellation, redacted outcome, idempotent cleanup, reconciliation |
| `backend/tests/runtime/` | 정책, identity, lifecycle, 장애 mapping, 정리 계약 test |
| `backend/tests/broker/` | Archive 공격, phase 및 durable cancellation, redaction, cleanup concurrency, event mapping, 공통 adapter conformance, live-state composition, CAS 중재, reconciliation, crash/restart 계약 test |
| `validation/manifests/m2-runtime-foundation.json` | 기계 판독 게이트 상태와 고정 source 증거 |
| `tools/check-m2.mjs` | drift, gate, 범위, hash 검증기 |

허용된 execution 의존 방향은 `domain worker -> SandboxSpec -> SandboxPolicy -> ValidatedSandboxSpec 및 JobIdentity -> RuntimeBackend`입니다. Durable state는 `RuntimeBackend` 일부가 아니라 `DurableJobStateStore`를 통한 별도 경계이며 outcome mapping, SQLite persistence, mock 전용 live composition, recovery는 제품 runtime 접근 권한을 부여하지 않고 이 경계에 의존합니다. 향후 런타임 adapter는 runtime protocol 뒤에 있어야 합니다. 향후 검토된 broker service는 진입 및 보안 게이트 승인 후 런타임 접근을 소유할 수 있는 유일한 구성 요소입니다.
