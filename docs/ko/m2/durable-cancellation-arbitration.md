# M2 durable external cancellation 중재

[English](../../en/m2/durable-cancellation-arbitration.md) | [M2 상태](README.md)

- 상태: 후보 계약 test 완료, 제품 비활성
- 작업 항목: RUN-007, BRK-006, BRK-007, BRK-008 확장
- Runtime 권한: mock 전용

이 범위는 HTTP, IPC, worker, 제품 runtime adapter, runtime socket, solver 실행을 추가하지 않고 typed 외부 cancellation을 기존 durable-state 후보에 연결합니다. `DurableBrokerComposition.cancel()`만 저장형 cancellation 진입점입니다. `SandboxBroker.cancel()` 직접 호출은 의도적으로 기존 non-persisted 계약을 유지합니다.

## Admission과 단일 승자 중재

Cancellation은 다음 순서를 따릅니다.

1. Startup recovery를 완료해 admission이 열린 상태여야 합니다.
2. Composition은 runtime에 접촉하기 전에 `DurableJobStateStore`에서 정확한 `JobIdentity`를 불러옵니다.
3. State가 없거나 terminal이거나 이미 `cancelling` 또는 `cleaning`이면 stable composition error로 거부합니다.
4. 호출자별 논리적 operation UUID와 새로운 내부 owner UUID로 불러온 revision에서 다음 fencing token의 `LiveStateSession`을 엽니다.
5. Session은 compare-and-swap으로 `cancelling/query`를 append합니다. Commit된 이 event가 durable cancellation intent이자 ownership takeover입니다.
6. CAS 승자만 runtime object를 조회하거나 변경할 수 있습니다. 경쟁 operation ID는 `cancellation-conflict`를 받고 runtime을 호출하지 않습니다.

Process-local cleanup coordinator는 broker 하나 안에서 중복 변경을 피합니다. 서로 독립적인 broker instance 사이의 정확성은 store CAS, commit된 owner generation, 제한된 durable lease가 보장합니다. Heartbeat는 job revision을 증가시키지 않고 정확한 generation을 갱신합니다. Cancellation만 live lease를 선점할 수 있으며 runtime 접촉 전에 다음 token을 commit합니다. Recovery는 이전 lease가 만료될 때까지 `owner-active`를 보고해야 합니다. 이는 단일 장비 후보이며 distributed 또는 multi-host lease가 아닙니다.

## 저장 lifecycle

실행 중인 container에는 다음 경계를 순서대로 저장합니다.

| 경계 | Durable state 및 phase | 순서 보장 |
|---|---|---|
| Intent | `cancelling/query` | 첫 runtime query 전에 commit |
| Kill 승인 | `cancelling/kill` | cancellation kill 전에 commit |
| Cleanup intent | cancelled classification을 가진 `cleaning/cleanup` | cleanup 전에 기록 |
| Terminal | `cancelled/kill` | 정확한 job cleanup과 object 0 재조회 뒤에만 기록 |

Runtime container와 volume이 이미 없으면 commit된 intent는 `RunResult`를 만들어 내지 않고 `cleaning`을 거쳐 `cancelled`로 수렴합니다. Volume만 남은 prefix도 제거한 뒤 같은 방식으로 수렴합니다. 이 idempotent 수렴은 durable intent admission 뒤에만 허용되며 broker 직접 cancellation은 기존 missing-container 동작을 유지합니다.

Complete-outcome mapper는 모든 `CancellationOutcome`을 cancellation intent로 취급합니다. 따라서 cleanup 미완료 mapping은 cancellation 결정을 잃지 않고 cancelled classification을 가진 recoverable `cleaning`으로 남습니다.

## Write 실패와 공개 결과

- Intent append가 실패하면 runtime 접촉을 금지합니다. Store 사용 불가는 `store-unavailable`, CAS 또는 transition 패배는 `cancellation-conflict`로 보고합니다.
- 이후 phase append가 일반 store 사용 불가로 실패하면 cancellation 진행은 멈추지만 fail-safe cleanup은 계속합니다. Owner 또는 revision이 더 새로운 값으로 대체된 경우 공개 outcome은 `failed:operation-fenced`이고 stale cleanup을 건너뛰며 현재 owner의 prefix가 authoritative 및 recoverable 상태로 남습니다.
- Runtime cancellation과 cleanup 뒤 terminal append가 실패해도 공개 outcome은 `failed`입니다. Runtime result가 cancelled라는 사실만으로 durable 완료를 보고하지 않습니다.
- Restart recovery는 `succeeded`를 만들어 내지 않습니다. Commit된 cancellation intent는 `cancelled`로 닫고 승인되지 않은 running prefix는 `failed:stale-state`로 닫습니다.

원본 database, filesystem, runtime, driver detail은 공개 outcome에 포함하지 않습니다.

## Crash 및 restart 계약

Cancellation operation 중단을 모델링하는 결정론적 checkpoint는 5곳입니다.

| 주입 checkpoint | 마지막 commit state | Restart 결과 |
|---|---|---|
| `before-intent` | `running` | Reconciliation 뒤 `failed:stale-state` |
| `after-intent` | `cancelling` | Reconciliation 뒤 `cancelled` |
| `after-cleaning-state` | `cleaning` | Reconciliation 뒤 `cancelled` |
| `after-cleanup` | object 0인 `cleaning` | `cancelled` |
| `after-final-state` | `cancelled` | 이미 terminal이므로 recovery scan에서 제외 |

Checkpoint exception은 계약 test를 위한 결정론적 동일 process crash 대역입니다. 외부 cancellation 자체를 OS process hard exit 또는 host 전원 손실로 검증했다고 주장하지 않습니다. 별도 SQLite recovery suite가 기존 commit claim hard-exit 증거를 계속 제공합니다.

## 검증과 남은 게이트

Cancellation 집중 test 8개는 admission 거부, SQLite 순서 및 owner-aware mapper 동등성, 이미 사라진 object 수렴, 독립 broker 호출자 2개의 CAS 단일 승자, intent write 실패, 이후 phase write 실패, terminal write 실패, restart checkpoint 5곳을 검사합니다. Ownership 경쟁 test 5개는 cancellation takeover와 stale owner fencing을 추가로 검사합니다. Owner lease 및 runtime fencing test 4개는 revision-neutral heartbeat renewal, expiry cancellation, stale 및 ambiguous token 거부, cross-job context 거부를 추가로 검사합니다. 전체 dependency-free Python suite는 test 133개를 포함하며 제품 runtime socket, network connection, solver를 열지 않습니다.

구현된 takeover 규칙은 [durable operation ownership 및 fencing](durable-operation-ownership.md)과 [owner lease, liveness, runtime fencing](owner-lease-runtime-fencing.md)에 설명합니다. 제품 service transport, worker integration, native Docker 및 Podman token 저장과 강제, runtime detection, native in-flight 취소, backup 및 restore, 전원 손실 자격 검증, clock-skew policy, multi-host coordination, runtime socket, solver 실행은 계속 차단 또는 대기 상태입니다.
