# M2 event mapping, adapter conformance, restart recovery

[English](../../en/m2/event-state-recovery.md) | [M2 상태](README.md)

## 상태와 범위

- 상태: engine-independent 계약 구현, gated
- Runtime 및 solver 접근: 없음
- SQLite durable-state 후보: test 완료, 비활성
- Phase-time execution wiring: 비활성 mock 전용 composition에 구현
- 외부 cancellation wiring: 미구현

이 계약은 완료된 redacted broker operation을 durable event로 바꾸는 방법, 모든 state adapter가 통과해야 할 공통 test, restart 뒤 recoverable state가 수렴하는 방법을 정의합니다. 기존 mapping 및 recovery 연결부는 engine-independent 상태를 유지하고 함께 제공하는 SQLite 후보는 표준 library local database와 test 전용 child process만 추가합니다. Service transport, runtime socket, 제품 Docker 또는 Podman adapter, worker 통합, solver 실행은 추가하지 않습니다.

## Broker event에서 durable state로의 mapping

`BrokerStateMapper`는 `BrokerOutcome` 또는 `CancellationOutcome`과 canonical operation UUID, 정규화된 runtime kind를 입력으로 받습니다. Source event sequence는 정확히 `1..N`이어야 하고 마지막 state는 outcome state와 같아야 하며 code가 있는 source event는 redacted `BrokerError`와 일치해야 합니다. 정규화된 error backend가 mapping context와 충돌하면 실패 폐쇄합니다.

| Source 또는 context | Durable field 또는 규칙 |
| --- | --- |
| 정확한 job identity | `job_id`와 전체 `JobIdentity` |
| Operation UUID | `operation_id`와 UUID v5 namespace |
| `BrokerEvent.sequence` | 양의 `operation_sequence` |
| Job ID와 source sequence | 결정론적 UUID v5 `event_id` |
| Broker state와 phase | `state`와 `phase` |
| 일치하는 공개 error | Stable `code`와 `retry`만 저장 |
| Mapping context | 정규화된 `backend` |
| Redacted run result 또는 cancellation intent | State 계약이 허용하는 곳에만 `classification` 저장 |
| Terminal state | Cleanup 완료일 때만 유효 |

Adapter는 event UUID를 다른 내용으로 재사용하거나 `(job_id, operation_id, operation_sequence)` slot을 다른 event로 재사용하는 것을 거부합니다. `StateEventRecorder`는 compare-and-swap revision으로 batch를 append합니다. 결정론적 ID 때문에 같은 event를 재전송하면 원래 commit snapshot이 반환되므로 batch 일부만 commit된 뒤에도 recorder가 이어서 기록할 수 있습니다.

Cleanup이 끝나지 않은 outcome은 terminal로 저장하지 않습니다. 마지막 source terminal event를 phase가 `cleanup`이고 stable cleanup error를 가진 recoverable `cleaning` event로 바꿉니다. Broker가 공개 outcome에 대해 이미 `failed`를 선택했더라도 orphan runtime object가 recovery scan에서 사라지는 일을 막습니다.

이 mapper는 계속 완료된 outcome을 입력으로 받습니다. `LiveStateSession`은 같은 결정론적 identity 규칙을 재사용하고 `DurableBrokerComposition`은 실행 중 각 phase append를 기다립니다. 명시적 경로는 mock 전용이고 제품 비활성 상태이며 broker 직접 실행과 외부 cancellation은 저장하지 않습니다.

## 공통 adapter conformance suite

`DurableStateStoreConformanceMixin`은 향후 모든 durable adapter가 재사용할 suite입니다. Concrete adapter는 같은 commit storage에 대한 새 handle과 재개방 handle을 제공합니다. Suite는 다음을 검사합니다.

1. Protocol shape, 빈 load, 빈 scan
2. 합법적인 단조 transition과 adapter 재개방 뒤 commit 가시성
3. 재개방 뒤 동일 event replay
4. Event UUID 및 operation slot 충돌 거부
5. 같은 revision에서 compare-and-swap winner가 정확히 하나인지 여부
6. Terminal job을 제외하는 bounded 및 sorted recovery pagination

Suite는 이제 concrete adapter 두 개에서 변경 없이 실행됩니다. `InMemoryStateStoreBacking`은 process-local handle semantics만 증명합니다. `SQLiteJobStateStore`는 file-backed commit 가시성, transactional CAS, schema fail-closed 동작, database lock redaction, fresh handle recovery pagination을 증명합니다. 별도의 [SQLite durable-state 후보 계약](sqlite-durable-state.md)은 migration, retention, durability 한계를 구분해 기록합니다.

## Crash 및 restart recovery 계약

`CrashRecoveryCoordinator`는 bounded recovery page 하나를 처리합니다.

1. Nonterminal snapshot을 scan합니다.
2. Compare-and-swap으로 결정론적 `cleaning` claim을 append합니다.
3. 정확한 job identity의 runtime object를 reconcile합니다.
4. Reconciliation이 미완료이면 code가 있는 `cleaning` event를 남깁니다.
5. Cancellation intent가 남아 있으면 `cancelled`, 그 외에는 `stale-state`가 있는 fail-safe `failed`를 append합니다.

Restart된 job을 `succeeded`로 복원하지 않습니다. Success는 정상 broker 경로와 검증된 artifact를 요구합니다. Recovery는 stale object를 제거하고 durable state를 닫거나 recoverable 상태로 유지하는 역할만 합니다.

결정론적 crash surrogate는 다음 경계 네 곳을 다룹니다.

| 주입 경계 | 중단 시 durable state | Mock runtime object | Restart 동작 |
| --- | --- | --- | --- |
| Claim 전 | 원래 recoverable revision | 유지 | Claim, reconcile, close |
| Claim 후 | `cleaning` claim commit | 유지 | Claim replay, reconcile, close |
| Reconcile 후 | `cleaning` claim commit | 완전한 reconciliation 뒤 0 | Claim replay, verify, close |
| Terminal append 후 | Terminal revision commit | 0 | Recovery scan에서 job 제외 |

결정론적 test는 모든 주입 중단 뒤 같은 fixture에 대한 새 state-store handle을 재개방합니다. 같은 recovery UUID는 이미 commit된 claim을 안전하게 replay합니다. Cleanup이 미완료이면 recoverable 상태로 남고 이후 새 recovery UUID가 다시 시도할 수 있습니다. 추가로 child process가 SQLite `after-claim` revision을 commit하고 `os._exit(91)`로 종료합니다. Parent process는 file을 다시 열어 revision 4를 확인하고 같은 claim을 replay한 뒤 terminal revision 5로 수렴합니다.

Concurrent coordinator가 같은 revision을 읽은 경우 compare-and-swap으로 claimant 하나만 성공합니다. 이는 distributed lease가 아닙니다. 이후 scan은 더 새로운 `cleaning` revision을 볼 수 있으며 multi-process ownership, lease expiry, fencing token, database 기반 arbitration은 구현하지 않았습니다.

## 증거와 남은 gate

Dependency-free Python suite는 현재 test 86개를 포함합니다. Test 34개는 memory 및 SQLite adapter 공통 suite, outcome 및 phase-time mapping, partial replay, startup admission, 부분 write cleanup, 결정론적 crash 경계 네 곳, cancellation recovery, 경쟁 claim, cleanup retry 수렴, schema 및 lock 동작, 별도 process hard exit를 검사합니다. Test는 격리된 SQLite file만 열며 runtime socket, network connection, 제품 runtime, solver는 열지 않습니다.

다음 state 마일스톤은 durable external cancellation과 restart-safe cancellation arbitration입니다. Backup 및 restore, power-loss 자격 검증, distributed fencing, 제품 활성화, 제품 Docker 및 Podman adapter는 계속 gate 상태입니다.
