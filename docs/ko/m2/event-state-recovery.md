# M2 event mapping, adapter conformance, restart recovery

[English](../../en/m2/event-state-recovery.md) | [M2 상태](README.md)

## 상태와 범위

- 상태: engine-independent 계약 구현, gated
- Runtime 및 solver 접근: 없음
- SQLite durable-state 후보: test 완료, 비활성
- Phase-time execution wiring: 비활성 mock 전용 composition에 구현
- 외부 cancellation wiring: 비활성 mock 전용 composition에 구현, 제품 비활성

이 계약은 완료된 redacted broker operation을 durable event로 바꾸는 방법, 모든 state adapter가 통과해야 할 공통 test, restart 뒤 recoverable state가 수렴하는 방법을 정의합니다. 기존 mapping 및 recovery 연결부는 engine-independent 상태를 유지하고 함께 제공하는 SQLite 후보는 표준 library local database와 test 전용 child process만 추가합니다. Service transport, runtime socket, 제품 Docker 또는 Podman adapter, worker 통합, solver 실행은 추가하지 않습니다.

## Broker event에서 durable state로의 mapping

`BrokerStateMapper`는 `BrokerOutcome` 또는 `CancellationOutcome`과 canonical operation UUID, 정규화된 runtime kind, owner 시도 UUID, fencing token을 입력으로 받습니다. Complete-outcome 기본값은 operation UUID를 token 1의 owner로 사용하며 phase-time composition은 실제 승인된 owner generation을 전달합니다. Source event sequence는 정확히 `1..N`이어야 하고 마지막 state는 outcome state와 같아야 하며 code가 있는 source event는 redacted `BrokerError`와 일치해야 합니다. 정규화된 error backend가 mapping context와 충돌하면 실패 폐쇄합니다.

| Source 또는 context | Durable field 또는 규칙 |
| --- | --- |
| 정확한 job identity | `job_id`와 전체 `JobIdentity` |
| Operation UUID | `operation_id`와 UUID v5 namespace |
| Owner generation | 모든 event의 `owner_id`, 양의 `fencing_token`, 제한된 `lease_duration_ms` |
| Current owner liveness | Job revision을 바꾸지 않고 갱신하는 mutable absolute lease expiry |
| `BrokerEvent.sequence` | 양의 `operation_sequence` |
| Job ID와 source sequence | 결정론적 UUID v5 `event_id` |
| Broker state와 phase | `state`와 `phase` |
| 일치하는 공개 error | Stable `code`와 `retry`만 저장 |
| Mapping context | 정규화된 `backend` |
| Redacted run result 또는 cancellation intent | State 계약이 허용하는 곳에만 `classification` 저장 |
| Terminal state | Cleanup 완료일 때만 유효 |

Adapter는 event UUID를 다른 내용으로 재사용하거나 `(job_id, operation_id, operation_sequence)` slot을 다른 event로 재사용하는 것을 거부합니다. `StateEventRecorder`는 compare-and-swap revision으로 batch를 append합니다. 결정론적 ID 때문에 같은 event를 재전송하면 원래 commit snapshot이 반환되므로 batch 일부만 commit된 뒤에도 recorder가 이어서 기록할 수 있습니다.

Cleanup이 끝나지 않은 outcome은 terminal로 저장하지 않습니다. 마지막 source terminal event를 phase가 `cleanup`이고 stable cleanup error를 가진 recoverable `cleaning` event로 바꿉니다. Broker가 공개 outcome에 대해 이미 `failed`를 선택했더라도 orphan runtime object가 recovery scan에서 사라지는 일을 막습니다.

이 mapper는 계속 완료된 outcome을 입력으로 받습니다. `LiveStateSession`은 같은 결정론적 identity 규칙을 재사용하고 `DurableBrokerComposition`은 execution과 외부 cancellation append를 작업 시점에 기다립니다. 외부 cancellation은 runtime query 전에 다음 owner generation으로 `cancelling/query`를 기록하고 cleanup까지 cancelled classification을 유지합니다. Recovery도 reconciliation 전에 다음 generation을 claim합니다. 명시적 경로는 mock 전용이고 제품 비활성 상태이며 broker 직접 execution과 cancellation은 저장하지 않습니다.

## 공통 adapter conformance suite

`DurableStateStoreConformanceMixin`은 향후 모든 durable adapter가 재사용할 suite입니다. Concrete adapter는 같은 commit storage에 대한 새 handle과 재개방 handle을 제공합니다. Suite는 다음을 검사합니다.

1. Protocol shape, 빈 load, 빈 scan
2. 합법적인 단조 transition과 adapter 재개방 뒤 commit 가시성
3. 재개방 뒤 동일 event replay
4. Event UUID 및 operation slot 충돌 거부
5. 같은 revision에서 compare-and-swap winner가 정확히 하나인지 여부
6. Adapter 재개방 뒤 owner takeover와 stale token 거부
7. Revision을 바꾸지 않고 재개방 뒤에도 보이는 live lease renewal
8. Owner expiry 뒤 verify, renew, append 거부
9. Live lease 동안 recovery 거부, cancellation 선점, expiry 뒤 recovery takeover
10. Terminal job을 제외하는 bounded 및 sorted recovery pagination

공통 conformance case 10개는 concrete adapter 두 개에서 변경 없이 실행됩니다. `InMemoryStateStoreBacking`은 process-local handle semantics만 증명합니다. `SQLiteJobStateStore`는 file-backed commit 가시성, transactional CAS 및 ownership 이전, 재개방 뒤 stale token 거부, schema fail-closed 동작, database lock redaction, fresh handle recovery pagination을 증명합니다. 별도의 [SQLite durable-state 후보 계약](sqlite-durable-state.md)은 migration, retention, durability 한계를 구분해 기록합니다.

## Crash 및 restart recovery 계약

`CrashRecoveryCoordinator`는 bounded recovery page 하나를 처리합니다.

1. Nonterminal snapshot을 scan합니다.
2. Current lease가 live이면 `owner-active`로 takeover를 거부하고, 그렇지 않으면 새로운 owner UUID, 다음 fencing token, 새로운 bounded lease를 사용해 compare-and-swap으로 `cleaning` claim을 append합니다.
3. 정확한 job identity의 runtime object를 reconcile합니다.
4. Reconciliation이 미완료이면 code가 있는 `cleaning` event를 남깁니다.
5. Cancellation intent가 남아 있으면 `cancelled`, 그 외에는 `stale-state`가 있는 fail-safe `failed`를 append합니다.

Restart된 job을 `succeeded`로 복원하지 않습니다. Success는 정상 broker 경로와 검증된 artifact를 요구합니다. Recovery는 stale object를 제거하고 durable state를 닫거나 recoverable 상태로 유지하는 역할만 합니다.

결정론적 crash surrogate는 다음 경계 네 곳을 다룹니다.

| 주입 경계 | 중단 시 durable state | Mock runtime object | Restart 동작 |
| --- | --- | --- | --- |
| Claim 전 | 원래 recoverable revision | 유지 | Claim, reconcile, close |
| Claim 후 | `cleaning` claim commit | 유지 | 새 owner generation이 takeover한 뒤 reconcile 및 close |
| Reconcile 후 | `cleaning` claim commit | 완전한 reconciliation 뒤 0 | 새 owner generation이 takeover한 뒤 verify 및 close |
| Terminal append 후 | Terminal revision commit | 0 | Recovery scan에서 job 제외 |

결정론적 test는 모든 주입 중단 뒤 같은 fixture에 대한 새 state-store handle을 재개방합니다. `recovery_id`는 report 상관관계를 유지하지만 각 recovery pass는 새로운 owner 시도를 사용합니다. Restart는 마지막 nonterminal generation의 lease가 live인 동안 기다리고 expiry 뒤에만 token을 증가시켜 takeover하며 cleanup 미완료 상태는 다른 owner 시도를 위해 recoverable 상태로 남습니다. 추가로 child process가 의도적으로 짧은 lease와 함께 SQLite `after-claim` revision 4를 commit하고 `os._exit(91)`로 종료합니다. Expiry 뒤 parent process는 file을 다시 열고 revision 5에 새로운 recovery owner를 commit한 뒤 terminal revision 6으로 수렴합니다.

Concurrent coordinator가 같은 revision을 읽은 경우 compare-and-swap으로 claimant 하나만 성공합니다. 이후 recovery는 nonterminal `cleaning` owner의 lease가 만료된 뒤 바로 다음 fencing token으로만 takeover할 수 있습니다. Guard가 적용된 await는 현재 generation을 heartbeat 처리하고 ownership을 잃으면 Python awaitable을 취소하며 strict bound mock runtime은 stale 또는 ambiguous context를 독립적으로 거부합니다. 이는 local durable liveness와 mock runtime fencing이며 distributed lease는 아닙니다. Multi-host coordination, bounded clock skew, native in-flight 취소, store commit과 runtime token 활성화 사이의 원자적 결합은 구현하지 않았습니다.

## 증거와 남은 gate

Dependency-free Python suite는 현재 test 154개를 포함합니다. Memory 및 SQLite adapter 공통 conformance case 10개, owner lease 및 runtime fencing 집중 case 4개, owner-aware outcome 및 phase-time mapping, partial replay, startup admission, 부분 write cleanup, recovery crash 경계 4곳, cancellation crash 경계 5곳, execution, cancellation, recovery ownership 경쟁 case 5개, cancellation recovery, 경쟁 claim, cleanup retry 수렴, schema v1 및 schema v2 migration, lease renewal 및 expiry, lock 동작, 별도 process hard exit를 검사합니다. Test는 격리된 SQLite file만 열며 runtime socket, network connection, 제품 runtime, solver는 열지 않습니다.

구현된 ownership 계약은 [durable operation ownership 및 fencing](durable-operation-ownership.md)과 [owner lease, liveness, runtime fencing](owner-lease-runtime-fencing.md)에 설명합니다. 제품 runtime의 native token 저장과 강제, native in-flight 취소, broker 통합 backup admission, 인증 transport, 보호된 control store rollback 저항성, power-loss 자격 검증, bounded clock skew, multi-host coordination, 제품 활성화, 제품 Docker 및 Podman adapter는 계속 gate 상태입니다.
