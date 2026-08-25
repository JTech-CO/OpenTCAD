# M2 runtime contract 기반

[English](../../en/m2/README.md)

M2는 `gated-active` 상태입니다. 계약 검토를 위해 runtime-neutral model, stable error, fail-closed policy validator, protocol, canonical input/output archive validator, 고정 job identity, phase 지정 cancellation, redacted 공개 event, process-local cleanup coordinator, 결정론적 broker-event mapping, 재사용 가능한 state-adapter conformance suite, durable-state interface, 비활성 file-backed SQLite 후보, crash/restart recovery coordinator, 비활성 mock 전용 phase-time composition, strict mock backend, 내부 mock broker orchestrator를 구현했습니다. 명시적인 비활성 composition은 mock 전용 test에서 execution과 외부 cancellation을 후보에 live wiring합니다. 외부 cancellation은 runtime query 전에 intent를 commit하고 revision CAS로 승자 하나를 정하며 restart 뒤에도 그 결정을 보존합니다. 새로운 내부 owner 시도와 단조 증가 fencing token은 검사된 store 및 broker 경계에서 execution, cancellation, recovery를 중재합니다. Composition은 제품 비활성 상태입니다. Docker 또는 Podman 제품 adapter, sandbox broker service transport, runtime detection, worker integration, runtime socket 접근, solver 실행은 없습니다.

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
| RUN-007 contract suite | 비활성 durable ownership 계약 test 완료 | Test 113개에 archive 공격, 20회 반복 2종, execution cancellation checkpoint 11곳, concurrent cleanup, phase-time execution 및 cancellation persistence, memory 및 SQLite adapter 공통 conformance case 10개, startup admission, 부분 write 처리, recovery crash 경계 4곳, cancellation crash 경계 5곳, ownership 경쟁 case 5개, schema v1 및 schema v2 migration, owner lease 및 runtime fencing case 4개, 별도 process hard exit, reconciliation, redaction, durable-state 의미 포함 |
| BRK-001 typed broker protocol | 기반 test 완료 | 내부 library가 typed spec과 canonical byte를 받고 redacted record를 반환 |
| BRK-003 managed volume lifecycle | Mock test 완료 | Create, stage, run, collect, container 제거, volume 제거, object 0 재조회 |
| BRK-004 archive defense | Input/output 기반 test 완료 | Canonical byte, traversal, link, device, 압축, metadata, collision, bomb, substitution, drift를 fail closed 처리 |
| BRK-006 recovery 및 reconciliation | 후보 fenced recovery test 완료 | Startup에서 admission 전에 recoverable page를 처리하고 각 recovery가 새로운 owner generation을 사용하며 더 새로운 recovery가 stale reconciliation을 fence 처리하고 commit된 cancellation intent는 cancelled, 승인되지 않은 running state는 failed로 닫음 |
| BRK-007 cancellation identity | Durable fenced mock cancellation test 완료 | 모든 job kind가 UUID identity 하나를 공유하고 execution checkpoint 11곳 모두 object 0으로 정리하며 외부 cancellation은 runtime 접촉 전에 다음 token으로 takeover |
| BRK-008 structured event/redaction | Durable owner-state mapping test 완료 | 결정론적 execution 및 cancellation mapping이 정규화 owner UUID와 fencing token을 저장하고 cleaning까지 cancelled classification을 유지하며 raw detail을 제외 |
| M2 종료 | 미충족 | Durable lease liveness와 strict mock runtime fencing은 test했지만 broker service, solver corpus, native token 강제를 갖춘 제품 runtime adapter, power-loss 증거, native platform 검증이 없음 |

## 구현된 경계

향후 worker는 server UUID, 승인 profile ID, job kind, 불변 image identity, 고정 input manifest, 제한된 resource limit, 승인 environment profile, 예상 output 이름만 포함한 `SandboxSpec`을 만들 수 있습니다. Model에는 command, shell, entrypoint, host path, mount, network mode, user, capability, security option, device, runtime socket 필드가 없습니다.

`SandboxPolicy.validate()`만 `ValidatedSandboxSpec`을 만들 수 있습니다. Backend는 이 검증 타입, opaque volume 및 container handle, stable 종료 사유만 받습니다. 필수 capability를 지원하지 않으면 `capability-missing`으로 거부하며 option을 제거하고 실행하지 않습니다.

Mock backend는 process를 실행하지 않고 socket도 소유하지 않습니다. 내부 broker library는 memory에서 정확한 비압축 input/output USTAR stream을 검증하고 staging에는 `ValidatedInputArchive`만 허용하며 byte와 manifest가 일치해야 `ValidatedArtifactArchive`를 만듭니다. Execution과 외부 cancellation에 고정 `JobIdentity`를 사용하고 typed execution cancellation checkpoint 11곳을 조회합니다. Cleanup, cancellation, reconciliation은 process-local job coordinator를 공유하며 container 다음 volume 순서로 제거하고, 관찰 뒤 이미 사라진 handle은 수렴으로 처리하며, cleanup 성공 보고 전에 managed object를 다시 조회합니다. Durable composition은 state 없음, terminal, cancelling, cleaning cancellation admission을 runtime 접촉 전에 거부하고 commit된 CAS 승자만 진행시킵니다.

`DurableJobStateStore`는 원자적 revision CAS, event UUID 및 operation slot idempotency, 허용 transition, terminal 불변성, redacted 저장 field, 제한된 recovery scan, 정확한 ownership 검사를 고정합니다. 모든 event는 논리적 operation UUID, 새로운 owner 시도 UUID, 단조 증가 fencing token을 포함합니다. `BrokerStateMapper`와 `StateEventRecorder`는 결정론적 complete-outcome mapping 및 partial replay를 정의합니다. 공통 conformance case 10개는 non-durable memory double과 `SQLiteJobStateStore`에서 모두 실행됩니다. Commit된 모든 event는 제한된 lease duration을 포함하고 renewal은 job revision이나 append-only event history를 바꾸지 않은 채 mutable current-lease row를 연장합니다. SQLite 후보는 schema v3, WAL, `synchronous=FULL`, `BEGIN IMMEDIATE`를 사용하고 정확한 schema v1 file은 v2를 거쳐, 정확한 schema v2 file은 v3으로 transaction 기반 migration하며 알 수 없는 schema를 실패 폐쇄하고 자동 retention을 수행하지 않습니다. `CrashRecoveryCoordinator`는 결정론적 recovery 경계 4곳을 검증하고 별도 Python process는 commit된 SQLite claim이 `os._exit` 뒤에도 남으며 reopen 뒤 새로운 recovery owner가 이전 owner를 fence 처리하고 수렴함을 증명합니다. `LiveStateSession`과 `DurableBrokerComposition`은 phase write를 기다리고 admission 전 startup recovery를 모두 처리하며 일반 write 실패 뒤 fail-safe cleanup을 계속하고 미완료 prefix를 recoverable 상태로 남깁니다. Execution은 token 1에서 시작하고 cancellation 및 expired-owner recovery takeover는 runtime 작업 전에 token을 증가시키며 live lease에 대한 recovery는 `owner-active`를 보고합니다. Ownership guard는 guard가 적용된 await의 전, 진행 중, 완료 후에 lease를 갱신하고 ownership을 잃으면 Python awaitable을 취소하며 expired 또는 stale owner의 append와 terminal state 기록을 막습니다. 모든 job lifecycle 호출은 `RuntimeFencingContext`를 통해 실행되며 strict mock runtime은 낮은 token, 같은 token의 owner 불일치, cross-job context, handle 불일치를 거부합니다. Stale 공개 outcome은 `operation-fenced`를 사용합니다. Broker 직접 execution과 cancellation은 기존 non-persisted 동작을 유지합니다. Service transport, 제품 활성화, 제품 Docker 또는 Podman token 저장과 강제, native in-flight 취소, backup 및 restore, multi-host coordination, power-loss 자격 검증은 없습니다.

## 산출물

- [RuntimeBackend ADR](runtime-backend-adr.md)
- [Sandbox broker threat model](broker-threat-model.md)
- [Broker 및 canonical archive 기반](broker-archive-foundation.md)
- [Output, cancellation, redaction 기반](output-cancellation-redaction.md)
- [Lifecycle cancellation, cleanup, state 계약](lifecycle-cleanup-state.md)
- [Event mapping, adapter conformance, restart recovery](event-state-recovery.md)
- [SQLite durable-state 후보](sqlite-durable-state.md)
- [비활성 live-state composition](live-state-composition.md)
- [Durable external cancellation 중재](durable-cancellation-arbitration.md)
- [Durable operation ownership 및 fencing](durable-operation-ownership.md)
- [Owner lease, liveness, runtime fencing](owner-lease-runtime-fencing.md)
- [`RuntimeBackend` protocol](../../../backend/app/runtime/protocol.py)
- [Runtime model](../../../backend/app/runtime/models.py)
- [Fail-closed policy](../../../backend/app/runtime/policy.py)
- [Stable error](../../../backend/app/runtime/errors.py)
- [Mock backend](../../../backend/app/runtime/mock_backend.py)
- [Canonical archive validator](../../../backend/app/broker/archive.py)
- [Mock broker orchestrator](../../../backend/app/broker/orchestrator.py)
- [Lifecycle cancellation 계약](../../../backend/app/broker/lifecycle.py)
- [Cleanup coordinator](../../../backend/app/broker/cleanup.py)
- [Durable-state interface](../../../backend/app/broker/state.py)
- [SQLite durable-state 후보](../../../backend/app/broker/sqlite_state.py)
- [Broker event-state mapper](../../../backend/app/broker/state_mapping.py)
- [Crash/restart recovery coordinator](../../../backend/app/broker/recovery.py)
- [Phase-time state session](../../../backend/app/broker/live_state.py)
- [비활성 durable broker composition](../../../backend/app/broker/state_composition.py)
- [Durable cancellation crash 경계](../../../backend/app/broker/cancellation_arbitration.py)
- [Runtime contract test](../../../backend/tests/runtime/test_mock_backend.py)
- [Archive defense test](../../../backend/tests/broker/test_archive.py)
- [Broker cleanup test](../../../backend/tests/broker/test_orchestrator.py)
- [Cancellation 및 redaction test](../../../backend/tests/broker/test_cancellation_redaction.py)
- [Phase cancellation test](../../../backend/tests/broker/test_lifecycle_control.py)
- [Concurrent cleanup test](../../../backend/tests/broker/test_cleanup_concurrency.py)
- [Durable-state interface test](../../../backend/tests/broker/test_state_store.py)
- [State-adapter conformance test](../../../backend/tests/broker/test_state_store_conformance.py)
- [SQLite conformance 및 hard-exit test](../../../backend/tests/broker/test_sqlite_state_store.py)
- [Event mapping test](../../../backend/tests/broker/test_state_mapping.py)
- [Crash/restart recovery test](../../../backend/tests/broker/test_recovery.py)
- [Live-state composition test](../../../backend/tests/broker/test_state_composition.py)
- [Durable cancellation 중재 test](../../../backend/tests/broker/test_durable_cancellation.py)
- [Durable operation ownership test](../../../backend/tests/broker/test_operation_ownership.py)
- [Owner lease 및 runtime fencing test](../../../backend/tests/broker/test_owner_lease_runtime_fencing.py)

다음 명령으로 기반을 검사합니다.

```sh
npm run check:m2
npm run test:runtime
```

의존성이 없는 이 contract suite는 Python 3.12부터 3.14까지 지원합니다. CI는 Python 3.12를 고정합니다.

## 다음 게이트

해결되지 않은 M1 진입 증거를 처리한 뒤 ADR과 threat model을 검토하고 승인해야 합니다. 다음 ownership 경계는 확정된 runtime fencing context를 제품 Docker 및 Podman object에 저장하고 native 수준에서 강제하며 in-flight 취소 또는 수렴 증거를 확보하는 것입니다. Backup 및 restore, power-loss 자격 검증, multi-host coordination, clock-skew policy, 제품 활성화는 이후 gate로 남습니다. 승인된 불변 engine profile과 해당 M2 진입 게이트가 생길 때까지 실제 Docker 및 Podman adapter는 차단합니다.
