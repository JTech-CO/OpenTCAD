# M2 lifecycle cancellation, cleanup, state 계약

[English](../../en/m2/lifecycle-cleanup-state.md) | [M2 상태](README.md)

- 상태: `gated-active`, mock 전용
- 작업 항목: BRK-006 및 BRK-007 계약 확장
- 제품 runtime 및 제품 state-store 활성화: 허용하지 않음

이 계약은 내부 mock broker 주위에 결정론적 cancellation 및 복구 연결부를 정의합니다. HTTP 또는 IPC service, solver, 제품 runtime adapter, host 압축 해제, runtime socket 접근은 추가하지 않습니다. 함께 제공하는 비활성 SQLite 후보는 제품 권한을 부여하지 않고 표준 library database와 test 전용 child process를 사용합니다.

## Lifecycle cancellation checkpoint

`SandboxBroker.execute()`는 in-process `CancellationSignal`을 받고 고정 checkpoint 11곳에서 조회합니다. `PhaseCancellation`은 결정론적 contract test 구현입니다.

| Checkpoint | Stable runtime phase | 도달 시 소유 object | Cancellation 동작 |
|---|---|---|---|
| `probe` | `probe` | 없음 | Runtime probe 전에 중단 |
| `policy` | `validate` | 없음 | Policy 검증 전에 중단 |
| `input-archive` | `input` | 없음 | Canonical input 검증 전에 중단 |
| `image` | `image` | 없음 | Image 검증 전에 중단 |
| `volume` | `volume` | 없음 | Volume 할당 전에 중단 |
| `input-stage` | `input` | Volume | Volume 제거 |
| `container-create` | `create` | Volume | Volume 제거 |
| `start` | `start` | Container 및 volume | 시작 전 container를 제거한 뒤 volume 제거 |
| `wait` | `wait` | 실행 중 container 및 volume | `TerminationReason.CANCELLATION`으로 kill한 뒤 정리 |
| `artifact-collection` | `artifact` | 종료된 container 및 volume | Runtime 결과와 output을 버리고 추가 kill 없이 정리 |
| `cleanup` | `cleanup` | 종료된 container 및 volume | 최종 정리 직전 경계에서 결과를 버린 뒤 cleanup 완료 |

Signal identity는 request의 `JobIdentity`와 정확히 같아야 하며 판정 값은 boolean이어야 합니다. Cancellation은 broker terminal outcome이 확정될 때까지 관찰할 수 있습니다. Cleanup은 cancellation으로 중단하지 않습니다. `cleanup` checkpoint의 요청은 예정 terminal state를 바꾸지만 object 제거와 object 0 검증을 건너뛰지 않습니다. 이 주입 연결부는 cancellation transport가 아니며 cross-process arbitration을 제공하지 않습니다.

## Concurrent cleanup idempotence

`JobCleanupCoordinator`는 canonical job UUID별로 process-local lease 하나를 부여합니다. Execution cleanup, typed cancellation, reconciliation이 같은 주입 가능 coordinator를 사용하므로 한 process의 여러 broker instance가 직렬화 경계를 공유할 수 있습니다.

모든 cleanup 시도는 다음 규칙을 따릅니다.

1. 정확한 job lease 획득
2. 해당 job 소유 handle만 조회하거나 조작
3. Container를 volume보다 먼저 제거
4. 관찰한 handle 조작 뒤 `container-not-found`와 `volume-not-found`가 반환되면 목표인 부재 상태에 수렴한 것으로 처리
5. 정확한 job을 다시 조회해 managed object가 0일 때만 성공 보고
6. 마지막 대기자가 끝나면 lease를 해제하고 registry에서 제거

따라서 동시 reconcile 호출에서는 첫 호출만 object를 제거해도 모든 report가 complete 상태가 됩니다. Typed cancellation과 reconcile이 동시에 실행돼도 object 0으로 수렴합니다. 이는 in-process idempotence 계약입니다. Durable distributed lease, ownership epoch, cross-process cancellation arbitration은 아직 구현하지 않았습니다.

## Durable state interface

`DurableJobStateStore`는 memory double과 SQLite 후보가 공유하는 비동기 operation 세 개를 정의합니다.

- `load(identity)`는 최신 불변 snapshot을 조회합니다.
- `append(event, expected_revision=...)`는 현재 revision을 원자적으로 비교하고 redacted event 하나를 추가합니다.
- `scan_recoverable(after=..., limit=...)`는 시작 시 복구를 위한 제한된 정렬 scan을 제공합니다.

`DurableJobEvent`에는 job UUID, event UUID, operation UUID와 양의 operation sequence, broker state, runtime phase, stable error code 및 retry disposition, 정규화된 backend, terminal classification, cleanup 완료 여부만 포함합니다. Raw detail, archive payload, command, secret, host path, runtime-native ID, database message는 포함하지 않습니다.

Revision은 1부터 시작해 1씩 증가합니다. Event UUID는 idempotency key이며 각 `(job_id, operation_id, operation_sequence)` slot은 고유합니다. 같은 event를 다시 보내면 원래 snapshot을 반환하고 어느 identity든 다른 내용으로 재사용하면 `event-conflict`로 실패합니다. 같은 expected revision에 대한 경쟁 write는 정확히 하나만 성공하고 나머지는 `revision-conflict`를 반환합니다. Transition 표는 명시적인 lifecycle 진행만 허용하고 `succeeded`, `cancelled`, `failed` 뒤의 변경을 거부합니다. Terminal event는 cleanup 완료 상태에서만 유효하므로 미완료 job은 recovery scan에 계속 나타납니다.

`InMemoryJobStateStore`는 non-durable contract double로 남습니다. `SQLiteJobStateStore`는 같은 conformance suite를 실행하고 schema v1, migration 거부, append-only retention, lock redaction, 별도 process hard-exit test를 추가한 비활성 file-backed 후보입니다. 명시적인 mock 전용 composition은 startup recovery 뒤 execution과 외부 cancellation phase event를 저장하지만 broker 직접 execution과 cancellation은 저장하지 않습니다. PostgreSQL, 자동 compaction, backup 및 restore, distributed lease, power-loss 자격 검증, 제품 활성화는 구현하거나 주장하지 않습니다.

## 검증과 남은 게이트

Python 3.12부터 3.14까지의 suite는 test 94개를 포함합니다. Case는 execution cancellation checkpoint 11곳 전체, durable intent-before-query 순서, 독립 호출자 CAS 중재, cancellation restart checkpoint 5곳, 잘못된 identity 및 boolean이 아닌 signal, concurrent reconciliation, 이미 사라진 object 수렴, 단조 증가 revision, replay 및 충돌, transition 거부, terminal 불변성, recovery pagination, redaction, startup admission, phase-time 순서, 부분 write cleanup을 검사합니다.

제품 Docker 및 Podman adapter, runtime socket, broker service transport, durable operation ownership fencing, distributed cleanup ownership, power-loss durability, 외부 cancellation transport, solver 실행은 기존 게이트에 따라 계속 차단 또는 대기 상태입니다. Mock 전용 저장 cancellation 계약은 [durable external cancellation 중재](durable-cancellation-arbitration.md)를 참고합니다.
