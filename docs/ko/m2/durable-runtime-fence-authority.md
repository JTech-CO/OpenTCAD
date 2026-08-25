# M2 durable runtime fence authority 및 활성화 복구

[English](../../en/m2/durable-runtime-fence-authority.md) | [M2 상태](README.md)

- 상태: process 간 local 후보 test 완료, 제품 비활성
- Authority adapter: 전용 SQLite schema v1
- 허용 runtime: strict mock만 사용
- 제품 Docker 및 Podman adapter: 미구현

## Authority 경계

`SQLiteRuntimeFenceAuthority`는 기존 `RuntimeFenceAuthority` protocol의 비활성 구현입니다. Canonical job UUID마다 현재 owner UUID와 양의 fencing token tuple 하나를 저장합니다. `activate()`는 정확한 tuple의 replay를 idempotent하게 허용하고 더 높은 token만 대체하며 낮은 token 또는 같은 token과 다른 owner 조합을 stable `operation-fenced`로 거부합니다. `verify()`는 정확한 현재 tuple만 허용합니다.

Authority는 전용 local file, schema version 1, WAL, `synchronous=FULL`, 정확한 schema 검사, 활성화를 위한 `BEGIN IMMEDIATE`를 사용합니다. 따라서 서로 다른 process와 adapter instance의 generation 변경은 SQLite write 경계에서 직렬화됩니다. 알 수 없는 schema, 제한된 timeout을 넘긴 database lock, filesystem 또는 SQLite 실패는 고정 detail `runtime-fence-authority-unavailable`을 가진 redacted `runtime-unavailable`로 변환됩니다. 공개 error와 `repr`은 database path를 노출하지 않습니다.

이 database는 schema v3 broker state database와 의도적으로 분리합니다. 같은 filesystem을 사용해도 두 commit이 원자적 동작이 되지는 않습니다.

## Store와 runtime 활성화 bridge

`DurableRuntimeFenceActivator`는 정확한 `DurableOperationOwnership`을 `RuntimeBackend.fence_authority`가 노출한 동일 authority에 연결합니다. Guard가 적용된 runtime 접촉 전에 다음 순서를 수행합니다.

1. `DurableJobStateStore`에서 정확한 live owner tuple과 job revision 확인
2. 일치하는 `RuntimeFencingContext`를 runtime authority에 단조 증가 방식으로 활성화
3. 정확한 store ownership과 revision 재확인
4. Authority에도 같은 runtime fence가 남아 있는지 재확인

`LiveStateSession`은 durable execution과 cancellation에 bridge를 사용합니다. `DurableOperationGuard`는 restart recovery에 사용합니다. Mock 전용 `DurableBrokerComposition`은 세 경로 모두에 bridge 하나를 전달합니다. 기존 lease renewal은 활성화 전에 계속 수행되고 heartbeat는 guard가 적용된 await 전후와 실행 중에 유지됩니다. 첫 store 검사와 authority 활성화 사이에 삽입된 takeover는 runtime operation 진입 전에 두 번째 store 검사에서 차단됩니다. 더 새로운 authority generation도 stale 호출자를 직접 거부합니다.

이 이중 검사는 실패 폐쇄형이지만 분산 transaction은 아닙니다. 마지막 검사 뒤 takeover가 commit될 수 있고 process가 state commit 뒤 authority 활성화 전에 종료될 수도 있습니다. 제품 정확성은 이 bridge를 원자적 동작으로 간주하면 안 됩니다.

## Crash 및 restart 계약

활성화 경계의 복구 규칙은 다음과 같습니다.

| 경계 | Durable 관찰 | Restart 동작 |
|---|---|---|
| Ownership commit 전 | 새 owner generation 없음 | 일반 admission 또는 recovery 재시도 |
| Ownership commit 후 authority 활성화 전 | State token이 authority token보다 높음 | Commit된 lease를 기다리거나 만료한 뒤 다음 token을 claim하고 reconciliation 전에 활성화를 replay |
| Authority 활성화 후 runtime 접촉 전 | 정확한 state 및 authority tuple 존재 | 같은 활성화를 idempotent하게 replay |
| Concurrent takeover 중 | Store 또는 authority 사후 검사 하나가 실패 | Fenced 결과를 반환하고 stale runtime 접촉 금지 |

별도 Python process는 authority token 2를 commit하고 `os._exit`를 호출합니다. 다시 연 authority는 token 2를 보존하고 token 1의 parent를 fence 처리합니다. 두 번째 hard-exit test는 token 2의 recovery claim을 commit하지만 활성화하지 않습니다. Reopen 뒤 recovery는 token 3을 claim하고 reconciliation 전에 token 3을 활성화하며 job을 닫고 버려진 token 2를 영구 거부합니다. Authority는 broker state를 만들지 않고 recovery는 authority token을 낮추지 않습니다.

## 재사용 가능한 증거

`RuntimeFenceAuthorityConformanceMixin`은 정확한 replay, 단조 증가 대체, 같은 token의 owner 불일치, concurrent generation 직렬화를 위한 공통 case 4개를 제공합니다. SQLite concrete suite는 정확한 WAL 및 FULL schema 검사, reopen durability, redacted lock 및 schema 실패, 별도 process hard-exit persistence를 추가합니다. Bridge test 4개는 정확한 commit ownership, 활성화 경계에 삽입된 takeover, composition execution 연결, state가 authority보다 앞선 restart gap을 검사합니다.

전체 runtime 및 broker suite는 test 133개를 포함합니다. Runtime socket을 열거나 solver를 시작하지 않으며 격리된 임시 SQLite file만 사용합니다.

## 제품 게이트

이 후보는 local host 증거만 제공합니다. Retention, backup, restore, corruption repair, multi-host consensus, 제한된 clock skew 증거, filesystem power-loss 자격 검증, 제품 service 연결이 없습니다. 이미 제출된 native 호출도 취소하지 않습니다. 제품 Docker 또는 Podman adapter는 native object에 같은 generation을 저장하고 강제해야 하며 composition에 노출한 동일 authority instance를 사용해야 합니다. 또한 재사용 가능한 두 conformance suite를 변경 없이 통과하고 native crash, power-loss, 안전한 in-flight 수렴 증거를 제공한 뒤에만 활성화할 수 있습니다.
