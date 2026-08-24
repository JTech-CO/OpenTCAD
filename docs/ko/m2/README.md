# M2 runtime contract 기반

[English](../../en/m2/README.md)

M2는 `gated-active` 상태입니다. 계약 검토를 위해 runtime-neutral model, stable error, fail-closed policy validator, protocol, canonical input/output archive validator, 고정 job identity, phase 지정 cancellation, redacted 공개 event, process-local cleanup coordinator, 결정론적 broker-event mapping, 재사용 가능한 state-adapter conformance suite, durable-state interface, 비활성 file-backed SQLite 후보, crash/restart recovery coordinator, 비활성 mock 전용 phase-time composition, strict mock backend, 내부 mock broker orchestrator를 구현했습니다. 명시적인 비활성 composition은 mock 전용 계약 test에서 execution phase event를 후보와 live wiring하지만 제품에는 활성화하지 않으며 외부 cancellation API도 저장하지 않습니다. Docker 또는 Podman 제품 adapter, sandbox broker service transport, runtime detection, worker integration, runtime socket 접근, solver 실행은 없습니다.

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
| RUN-007 contract suite | 비활성 live-state startup 계약 test 완료 | Test 86개에 archive 공격, 20회 반복 2종, cancellation checkpoint 11곳, concurrent cleanup, phase-time event persistence, memory 및 SQLite adapter conformance, startup admission, 부분 write 처리, 주입 crash 경계 4곳, 별도 process hard exit, reconciliation, redaction, durable-state 의미 포함 |
| BRK-001 typed broker protocol | 기반 test 완료 | 내부 library가 typed spec과 canonical byte를 받고 redacted record를 반환 |
| BRK-003 managed volume lifecycle | Mock test 완료 | Create, stage, run, collect, container 제거, volume 제거, object 0 재조회 |
| BRK-004 archive defense | Input/output 기반 test 완료 | Canonical byte, traversal, link, device, 압축, metadata, collision, bomb, substitution, drift를 fail closed 처리 |
| BRK-006 recovery 및 reconciliation | 후보 startup recovery gate test 완료 | 공유 job lease로 mock cleanup 직렬화, startup에서 admission 전에 recoverable page 처리, 공통 adapter test로 memory 및 SQLite CAS 검증, commit된 SQLite claim이 별도 process hard exit 뒤에도 남고 정확한 job reconciliation으로 수렴 |
| BRK-007 cancellation identity | Phase 행렬 test 완료 | 모든 job kind가 UUID identity 하나를 공유하고 execution checkpoint 11곳 모두 정확한 object 0 cleanup으로 취소 |
| BRK-008 structured event/redaction | Phase-time mapping 및 redaction test 완료 | 결정론적 complete-outcome 및 live execution mapping은 정규화 field만 저장하고 공개 및 저장 shape는 raw detail 제외 |
| M2 종료 | 미충족 | Mock 전용 phase-time execution wiring은 test했지만 외부 cancellation persistence, broker service, solver corpus, 제품 runtime adapter, power-loss 증거, distributed ownership, native platform 검증이 없음 |

## 구현된 경계

향후 worker는 server UUID, 승인 profile ID, job kind, 불변 image identity, 고정 input manifest, 제한된 resource limit, 승인 environment profile, 예상 output 이름만 포함한 `SandboxSpec`을 만들 수 있습니다. Model에는 command, shell, entrypoint, host path, mount, network mode, user, capability, security option, device, runtime socket 필드가 없습니다.

`SandboxPolicy.validate()`만 `ValidatedSandboxSpec`을 만들 수 있습니다. Backend는 이 검증 타입, opaque volume 및 container handle, stable 종료 사유만 받습니다. 필수 capability를 지원하지 않으면 `capability-missing`으로 거부하며 option을 제거하고 실행하지 않습니다.

Mock backend는 process를 실행하지 않고 socket도 소유하지 않습니다. 내부 broker library는 memory에서 정확한 비압축 input/output USTAR stream을 검증하고 staging에는 `ValidatedInputArchive`만 허용하며 byte와 manifest가 일치해야 `ValidatedArtifactArchive`를 만듭니다. Execution과 외부 cancellation에 고정 `JobIdentity`를 사용하고 typed cancellation checkpoint 11곳을 조회합니다. Cleanup, cancellation, reconciliation은 process-local job coordinator를 공유하며 container 다음 volume 순서로 제거하고, 관찰 뒤 이미 사라진 handle은 수렴으로 처리하며, cleanup 성공 보고 전에 managed object를 다시 조회합니다.

`DurableJobStateStore`는 원자적 revision CAS, event UUID 및 operation slot idempotency, 허용 transition, terminal 불변성, redacted 저장 field, 제한된 recovery scan을 고정합니다. `BrokerStateMapper`와 `StateEventRecorder`는 결정론적 complete-outcome mapping 및 partial replay를 정의합니다. 변경하지 않은 공통 conformance suite는 non-durable memory double과 `SQLiteJobStateStore`에서 모두 실행됩니다. SQLite 후보는 append-only schema v1, WAL, `synchronous=FULL`, `BEGIN IMMEDIATE`를 사용하고 알 수 없는 schema version을 fail closed 처리하며 자동 retention을 수행하지 않습니다. `CrashRecoveryCoordinator`는 결정론적 mock 경계 4곳을 검증하고 별도 Python process는 commit된 SQLite claim이 `os._exit` 뒤에도 남아 reopen 후 수렴함을 증명합니다. `LiveStateSession`과 `DurableBrokerComposition`은 phase write를 기다리고 admission 전 startup recovery를 모두 처리하며 write 실패 뒤에도 cleanup을 계속하고 미완료 prefix를 recoverable 상태로 남기는 명시적인 mock 전용 경로를 제공합니다. Broker 직접 실행과 외부 cancellation은 기존 non-persisted 동작을 유지합니다. Service transport, 제품 활성화, distributed fencing, backup 및 restore, power-loss 자격 검증은 없습니다.

## 산출물

- [RuntimeBackend ADR](runtime-backend-adr.md)
- [Sandbox broker threat model](broker-threat-model.md)
- [Broker 및 canonical archive 기반](broker-archive-foundation.md)
- [Output, cancellation, redaction 기반](output-cancellation-redaction.md)
- [Lifecycle cancellation, cleanup, state 계약](lifecycle-cleanup-state.md)
- [Event mapping, adapter conformance, restart recovery](event-state-recovery.md)
- [SQLite durable-state 후보](sqlite-durable-state.md)
- [비활성 live-state composition](live-state-composition.md)
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

다음 명령으로 기반을 검사합니다.

```sh
npm run check:m2
npm run test:runtime
```

의존성이 없는 이 contract suite는 Python 3.12부터 3.14까지 지원합니다. CI는 Python 3.12를 고정합니다.

## 다음 게이트

해결되지 않은 M1 진입 증거를 처리한 뒤 ADR과 threat model을 검토하고 승인해야 합니다. 다음 state 범위는 runtime 권한을 넓히지 않는 durable external cancellation과 restart-safe cancellation arbitration입니다. Backup 및 restore, power-loss 자격 검증, distributed fencing, 제품 활성화는 이후 gate로 남습니다. 승인된 불변 engine profile과 해당 M2 진입 게이트가 생길 때까지 실제 Docker 및 Podman adapter는 차단합니다.
