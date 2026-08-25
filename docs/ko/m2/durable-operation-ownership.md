# M2 durable operation ownership 및 fencing

[English](../../en/m2/durable-operation-ownership.md) | [M2 상태](README.md)

- 상태: 후보 계약 test 완료, 제품 비활성
- 대상 operation: execution, 외부 cancellation, restart recovery
- 권한: mock runtime에서만 사용하는 durable store 검사

이 범위는 승인된 각 operation에 명시적인 durable owner generation을 부여합니다. Durable record의 ownership을 이미 잃은 owner가 검사된 broker 경계에서 계속 진행하는 것을 막습니다. Service, worker transport, 제품 Docker 또는 Podman adapter, runtime socket, solver 실행은 추가하지 않습니다.

## Ownership model

`DurableOperationOwnership`은 정확한 `JobIdentity`, 논리적 `operation_id`, owner 시도 UUID인 `owner_id`, 양의 정수 `fencing_token`을 포함합니다. 모든 durable event는 이 값 네 개를 저장합니다.

- 새 execution은 token `1`과 새로운 내부 owner UUID로 시작합니다. 같은 논리적 operation UUID를 사용한 반복 호출도 서로 다른 owner 시도로 경쟁합니다.
- 한 owner의 이후 event는 같은 operation UUID와 token을 유지해야 합니다.
- Cancellation takeover는 runtime query 전에 바로 다음 token으로 `cancelling`을 commit합니다.
- Recovery는 reconciliation 전에 바로 다음 token으로 `cleaning`을 commit합니다. 더 새로운 recovery는 중단된 recovery를 다시 takeover하면서 token을 한 번 더 증가시킬 수 있습니다.
- Generation을 건너뛴 takeover, 다른 owner의 token 재사용, 합법적인 takeover 없이 operation identity 변경, 허용되지 않은 state에서의 takeover는 `ownership-conflict`로 실패 폐쇄합니다.

Revision compare-and-swap과 fencing token은 서로 다른 역할을 합니다. Revision은 모든 event 순서를 정하고 token은 현재 owner generation을 식별합니다. `verify_ownership()`은 정확한 owner tuple을 요구하며 전달된 경우 마지막으로 관찰한 revision도 정확히 일치해야 합니다. 따라서 같은 owner라도 다른 writer가 job을 진행시킨 뒤 중복 작업을 계속할 수 없습니다.

## 검사 경계

`LiveStateSession`은 execution의 probe, image 준비, volume 생성, input staging, container 생성, start, wait, artifact 수집, kill, cleanup 변경, 최종 object 0 조회 전에 ownership을 확인합니다. Durable cancellation은 query와 kill 전에 takeover ownership을 확인합니다. Recovery는 reconciliation을 `DurableOperationGuard`로 감싸고 query, 각 변경 또는 재시도, 최종 확인 query 전에 검사합니다.

Stale execution 또는 cancellation이 다른 owner나 revision을 발견하면 stable `operation-fenced`가 있는 공개 `failed`를 반환하고 stale cleanup 변경을 건너뛰며 durable terminal state를 append할 수 없습니다. Stale recovery item은 같은 공개 code와 함께 `ownership-conflict`를 보고합니다. 원본 database 또는 runtime detail은 공개하지 않습니다.

## SQLite schema 및 호환성

비활성 SQLite 후보는 이제 schema version `2`를 사용합니다. Append transaction은 memory double과 같은 ownership 규칙을 적용합니다. `verify_ownership()`은 최신 commit snapshot을 읽고 정확한 owner tuple과 선택적 expected revision을 요구합니다. 공통 adapter conformance suite에는 adapter를 다시 열고 ownership을 이전한 뒤 이전 token이 fenced 상태인지 확인하는 일곱 번째 case가 추가됐습니다.

기존 schema version `1` file은 event를 삭제하지 않고 하나의 transaction에서 전진 migration합니다. 각 과거 operation은 첫 revision 순서에 따라 owner generation이 되며 기존 operation UUID를 migration된 owner UUID로 사용합니다. 알 수 없는 이후 version과 schema 불일치는 계속 실패 폐쇄합니다. 자동 downgrade, compaction, backup, restore는 구현하지 않았습니다.

## 경쟁 상태 증거

집중 test 5개가 operation 사이의 ownership을 검사합니다.

1. 같은 논리적 operation UUID를 사용하는 execution caller 두 개 중 하나만 runtime을 호출하고 다른 하나는 fenced 처리됩니다.
2. Cancellation이 live execution을 takeover하면 stale execution은 wait 또는 cleanup에 진입하지 못합니다.
3. Execution 내부 cancellation 직전에 ownership이 이전되면 stale owner는 runtime object를 kill하거나 cleanup하지 못합니다.
4. Recovery가 runtime query 전 cancellation을 takeover하면 recovery만 mock runtime을 변경합니다.
5. 더 새로운 recovery가 이전 reconciler를 runtime object 변경 전에 fence 처리합니다.

전체 dependency-free Python suite는 test 102개를 포함합니다. 제품 runtime, network service, runtime socket, solver를 호출하지 않습니다.

## 정확한 한계와 다음 경계

이는 협력형 application-level fencing이며 runtime 강제형 또는 distributed fencing이 아닙니다. Ownership 검사와 이어지는 mock runtime 호출은 하나의 원자적 동작이 아닙니다. 검사가 성공한 뒤 발생한 takeover는 이미 진행 중인 호출을 취소할 수 없고 mock runtime은 object 또는 변경 요청의 token을 검사하지 않습니다. Heartbeat, lease expiry, 실패 owner detector, multi-host lock, database service, power-loss 자격 검증, 제품 adapter 통합도 없습니다.

다음 ownership 경계는 durable owner liveness 및 lease-expiry policy와 향후 제품 runtime adapter에서의 fencing token 전달 및 강제입니다. 이 작업은 불변 engine profile, M1 증거, 제품 adapter 검토, 기존 no-socket 제품 경계에 따라 계속 gate 상태입니다.
