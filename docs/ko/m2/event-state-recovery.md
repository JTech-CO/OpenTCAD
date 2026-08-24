# M2 event mapping, adapter conformance, restart recovery

[English](../../en/m2/event-state-recovery.md) | [M2 상태](README.md)

## 상태와 범위

- 상태: engine-independent 계약 구현, gated
- Runtime 및 solver 접근: 없음
- Durable database adapter: 미구현
- Live broker-to-store wiring: 미구현

이 작업은 완료된 redacted broker operation을 durable event로 바꾸는 방법, 향후 모든 state adapter가 통과해야 할 공통 test, process restart 뒤 recoverable state가 수렴하는 방법을 정의합니다. 엄격한 memory 기반 double만 사용합니다. Service transport, database driver, runtime socket, 제품 Docker 또는 Podman adapter, worker 통합, solver 실행은 추가하지 않습니다.

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

이 mapper는 완료된 outcome을 입력으로 받습니다. 실행 중인 broker가 각 phase에서 state를 append하도록 연결한 것은 아닙니다. Live broker-to-store wiring은 별도 gate로 남습니다.

## 공통 adapter conformance suite

`DurableStateStoreConformanceMixin`은 향후 모든 durable adapter가 재사용할 suite입니다. Concrete adapter는 같은 commit storage에 대한 새 handle과 재개방 handle을 제공합니다. Suite는 다음을 검사합니다.

1. Protocol shape, 빈 load, 빈 scan
2. 합법적인 단조 transition과 adapter 재개방 뒤 commit 가시성
3. 재개방 뒤 동일 event replay
4. Event UUID 및 operation slot 충돌 거부
5. 같은 revision에서 compare-and-swap winner가 정확히 하나인지 여부
6. Terminal job을 제외하는 bounded 및 sorted recovery pagination

현재 concrete run은 별도 adapter handle이 process-local fixture 하나를 공유할 수 있도록 `InMemoryStateStoreBacking`을 사용합니다. 이는 suite와 handle 재개방 semantics만 증명합니다. Process가 끝나면 backing이 사라지므로 crash durability, transaction isolation, migration 안전성, backup, retention, database availability 동작은 증명하지 않습니다.

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

Test는 모든 주입 중단 뒤 같은 fixture에 대한 새 state-store handle을 재개방합니다. 같은 recovery UUID는 이미 commit된 claim을 안전하게 replay합니다. Cleanup이 미완료이면 recoverable 상태로 남고 이후 새 recovery UUID가 다시 시도할 수 있습니다.

Concurrent coordinator가 같은 revision을 읽은 경우 compare-and-swap으로 claimant 하나만 성공합니다. 이는 distributed lease가 아닙니다. 이후 scan은 더 새로운 `cleaning` revision을 볼 수 있으며 multi-process ownership, lease expiry, fencing token, database 기반 arbitration은 구현하지 않았습니다.

## 증거와 남은 gate

Dependency-free Python suite는 현재 test 67개를 포함합니다. 새 test 15개는 공통 adapter suite, outcome mapping과 partial replay, crash 경계 네 곳, cancellation recovery, 경쟁 claim, cleanup retry 수렴을 검사합니다. Runtime socket, database, network connection, solver를 여는 test는 없습니다.

다음 state 마일스톤은 실제 durable adapter 선택과 검토, 별도 process에서 transaction 및 restart 동작 증명, migration 및 retention 정책 정의, phase-time broker event와 adapter 연결을 요구합니다. 제품 Docker 및 Podman adapter는 기존 M2 진입 및 보안 gate에 따라 계속 차단합니다.
