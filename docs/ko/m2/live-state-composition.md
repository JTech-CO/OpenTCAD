# M2 비활성 live-state composition

[English](../../en/m2/live-state-composition.md) | [M2 상태](README.md)

## 상태와 권한

- 상태: 계약 test를 갖춘 비활성 mock 전용 composition 후보
- 제품 활성화 flag: `false`
- 제품 Docker 및 Podman runtime kind: constructor에서 거부
- Service, worker, runtime socket, network, solver 권한: 없음
- Phase-time execution persistence: 명시적으로 선택하는 composition을 통해 구현
- Durable 외부 cancellation: 명시적인 composition에서만 구현, `SandboxBroker.cancel()` 직접 호출은 non-persisted 유지

`DurableBrokerComposition`은 기존 broker lifecycle과 `DurableJobStateStore`를 연결하지만 이를 제품 실행 경로로 만들지 않습니다. `SandboxBroker.execute()`와 `SandboxBroker.cancel()`을 직접 호출하면 기존 memory event 동작을 유지합니다. Composition은 `RuntimeKind.MOCK`만 허용하므로 향후 제품 backend가 추가되어도 이 후보가 암묵적으로 활성화되지 않습니다.

## Admission 전 startup

직렬화된 `startup()` 호출 하나가 완료되어야 `execute()` 또는 durable `cancel()`이 작업을 받습니다.

1. Recoverable snapshot을 제한된 page 하나씩 scan합니다.
2. 결정론적 page recovery UUID를 사용해 각 revision을 compare-and-swap으로 claim합니다.
3. 정확한 job identity의 runtime object를 reconcile합니다.
4. 모든 cursor를 처리합니다.
5. Recoverable item 하나를 찾는 최종 scan을 수행합니다.
6. 최종 scan이 비어 있을 때만 ready 상태를 공개합니다.

Reconciliation이 미완료이면 job은 `cleaning`에 남고 admission gate도 닫힌 상태를 유지합니다. Store 실패는 공개 세부 정보가 없는 stable `store-unavailable` composition error가 됩니다. Ready 상태 뒤의 반복 startup 호출은 처음 완료된 report를 반환합니다. Admission gate는 계속 단일 process입니다. Durable store는 제한된 owner lease를 별도로 강제합니다. Startup recovery는 이전 owner가 live인 동안 `owner-active`를 보고하고 gate를 닫은 상태로 유지하며 expiry 뒤에만 claim합니다. Guard가 적용된 runtime await는 정확한 generation을 호출 전, 진행 중, 완료 후에 갱신합니다. 이는 local liveness 계약이며 distributed 또는 multi-host lease가 아닙니다.

## Phase-time 순서

`LiveStateSession`은 admission된 job 하나, canonical operation UUID 하나, 정규화 backend 하나, expected revision 하나를 결합합니다. `BrokerStateMapper`와 같은 결정론적 UUID v5 event ID를 만들고 각 compare-and-swap append를 기다립니다.

| Durable event | Commit이 먼저 완료되어야 하는 작업 |
| --- | --- |
| `validating` | Runtime probe |
| `preparing` | Image 확인 및 volume 할당 |
| `running` | Runtime wait |
| `collecting` | Artifact 전달 및 검증 |
| `cancelling` | Execution 경로 cancellation kill |
| `cleaning` | Object cleanup |
| Terminal state | 최종 outcome 반환 |

Composition은 session을 만들기 전에 state를 load합니다. Execution은 기존 snapshot이 있으면 runtime probe 전에 거부합니다. Durable cancellation은 기존 nonterminal state를 요구하고 cancellation 또는 cleanup intent가 이미 있으면 거부하며 runtime query 전에 `cancelling/query`를 commit합니다. 경쟁 operation ID는 revision CAS로 보호합니다. Phase-time record에는 정규화된 state, phase, code, retry, backend, classification, cleanup 완료 field만 포함합니다.

## 부분 write 동작

첫 state-store 실패가 발생하면 session은 failed 상태가 됩니다. 이후 phase emission은 no-op이 되어 store 장애가 broker의 `finally` cleanup 경로를 막지 못하게 합니다.

| 실패 지점 | 실행 동작 | Durable 결과 |
| --- | --- | --- |
| `preparing` commit 전 | Image 또는 volume 할당을 시작하지 않음 | 마지막 `validating` revision이 recoverable 상태로 유지됨 |
| `running` commit 전 | 이후 실행을 중단하고 할당된 object를 제거함 | 마지막 `preparing` revision이 recoverable 상태로 유지됨 |
| Cleanup 또는 terminal commit | Cleanup을 계속 수행함 | 마지막 nonterminal prefix가 recoverable 상태로 유지됨 |
| 성공 실행의 terminal commit 실패 | 공개 success를 `failed`로 강등하고 artifact를 제거함 | Commit된 `cleaning` prefix를 startup recovery가 `failed:stale-state`로 닫음 |

공개 state write 실패는 `invalid-state`, infrastructure retry 구분, 실패 phase, 정규화된 mock backend만 사용합니다. Driver message와 database path는 공개 outcome에 복사하지 않습니다. Recovery는 success를 만들어 내지 않습니다.

Runtime cleanup 자체가 미완료이면 공개 마지막 event는 `failed`일 수 있지만 durable 마지막 append는 code가 있는 `cleaning`에 머뭅니다. 따라서 recovery scan에서 계속 보이며 complete-outcome mapper 계약과 일치합니다.

## 증거와 남은 게이트

Execution composition test 9개는 startup admission 순서, SQLite phase 순서 및 owner-aware mapper 동등성, write 실패, restart 수렴, 기존 job 거부, stale object reconciliation, 미완료 recovery의 gate 폐쇄, 제품 runtime 거부를 검사합니다. Durable cancellation test 8개는 CAS 단일 승자, intent-before-query 순서, 이미 사라진 object 수렴, write 실패, restart checkpoint 5곳을 검사합니다. Ownership test 5개는 execution, cancellation, recovery takeover 경쟁을 추가합니다. Owner lease 및 runtime fencing test 4개는 heartbeat renewal, expiry cancellation, stale-token 강제, cross-job 거부를 추가합니다. 전체 dependency-free Python suite는 test 133개를 포함하며 제품 runtime이나 solver를 호출하지 않습니다.

구현된 ownership 경계는 [durable operation ownership 및 fencing](durable-operation-ownership.md)과 [owner lease, liveness, runtime fencing](owner-lease-runtime-fencing.md)에 설명합니다. 제품 service transport, worker integration, 제품 runtime의 native token 저장과 강제, multi-host coordination, clock-skew policy, retention compaction, backup 및 restore, host 전원 손실 자격 검증, runtime socket, solver 실행은 계속 차단 또는 대기 상태입니다.
