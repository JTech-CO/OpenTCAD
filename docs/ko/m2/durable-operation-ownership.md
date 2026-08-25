# M2 durable operation ownership 및 fencing

[English](../../en/m2/durable-operation-ownership.md) | [M2 상태](README.md)

- 상태: 후보 계약 test 완료, 제품 비활성
- 대상 operation: execution, 외부 cancellation, restart recovery
- 권한: durable lease 검사와 strict bound mock runtime 강제만 허용

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

`LiveStateSession`은 guard가 적용된 runtime await 전, 진행 중, 완료 후에 정확한 live ownership을 갱신합니다. Probe와 image 준비는 global operation으로 남지만 heartbeat guard를 적용합니다. Volume 생성, input staging, container 생성, start, wait, artifact 수집, kill, cleanup 변경, 정확한 job의 object 0 조회를 포함한 모든 job lifecycle 호출은 guard의 정확한 `RuntimeFencingContext`와 함께 `RuntimeBackend.bind_job()`을 통해 실행합니다. Durable cancellation은 query와 kill 전에 commit된 takeover context를 bind합니다. Recovery는 lease가 만료된 뒤에만 claim하고 같은 bound context로 reconciliation을 수행합니다.

Stale 또는 expired execution이나 cancellation이 renewal을 잃으면 Python awaitable을 취소하고 stable `operation-fenced`가 있는 공개 `failed`를 반환하며 stale cleanup 변경을 건너뛰고 durable terminal state를 append하지 못합니다. Strict mock runtime은 낮은 token, 다른 owner와 결합한 같은 token, cross-job context, 다른 job의 handle을 독립적으로 거부합니다. Stale recovery item은 `ownership-conflict`를 보고하고 이전 lease가 live이면 takeover 없이 `owner-active`를 보고합니다. 원본 database 또는 runtime detail은 공개하지 않습니다.

## SQLite schema 및 호환성

비활성 SQLite 후보는 이제 schema version `3`을 사용합니다. Append-only `job_events` row는 commit된 각 lease duration을 보존하고 mutable `job_leases` row 하나가 현재 owner tuple과 절대 expiry를 저장합니다. `renew_ownership()`은 정확한 live lease row만 갱신하므로 heartbeat renewal은 job revision을 바꾸거나 durable event를 append하지 않습니다. Append, renew, verify, recovery scan은 memory double과 같은 expiry 및 ownership 규칙을 강제합니다.

기존의 정확한 schema version `1` file은 event를 삭제하지 않고 transaction 하나에서 version `2`를 거쳐 version `3`으로 migration하며 정확한 version `2` file은 version `3`으로 바로 migration합니다. 과거 operation generation은 보존하고 현재 lease는 보수적으로 expired 상태로 만들어 upgrade 뒤 recovery가 진행할 수 있게 합니다. 알 수 없는 이후 version이나 event 또는 lease table 불일치는 계속 실패 폐쇄합니다. 자동 downgrade, compaction, backup, restore는 구현하지 않았습니다.

## 경쟁 상태 증거

집중 test 5개가 operation 사이의 ownership을 검사합니다.

1. 같은 논리적 operation UUID를 사용하는 execution caller 두 개 중 하나만 runtime을 호출하고 다른 하나는 fenced 처리됩니다.
2. Cancellation이 live execution을 takeover하면 stale execution은 wait 또는 cleanup에 진입하지 못합니다.
3. Execution 내부 cancellation 직전에 ownership이 이전되면 stale owner는 runtime object를 kill하거나 cleanup하지 못합니다.
4. Recovery가 runtime query 전 cancellation을 takeover하면 recovery만 mock runtime을 변경합니다.
5. 더 새로운 recovery가 이전 reconciler를 runtime object 변경 전에 fence 처리합니다.

Owner lease test 4개는 revision을 바꾸지 않는 heartbeat renewal, expired in-flight Python awaitable 취소, stale 및 ambiguous owner 거부, cross-job 거부를 증명합니다. 재사용 가능한 runtime-fence suite는 공통 adapter case 5개와 authority, parser, post-mutation 집중 case 3개를 추가합니다. 정확한 mock object label 저장, adapter instance 사이의 공유 authority, takeover 제한, operation 후 stale 결과 차단, cleanup 수렴을 증명합니다. 전체 dependency-free Python suite는 test 133개를 포함합니다. 제품 runtime, network service, runtime socket, solver를 호출하지 않습니다.

## 정확한 한계와 다음 경계

비활성 local 후보에는 durable heartbeat liveness, lease expiry, process-local 기준 authority, 전용 SQLite process 간 authority 후보, 이중 확인형 store와 runtime 활성화 bridge, strict mock adapter의 native object fencing 강제를 구현했습니다. Store commit과 runtime 활성화는 하나의 원자적 동작이 아닙니다. Python awaitable을 취소해도 이전에 제출된 native runtime 요청이 취소됐음을 증명하지 않습니다. Operation 후 검사는 stale 성공을 차단하고 current-owner cleanup 수렴을 허용하지만 완료된 변경을 되돌릴 수는 없습니다. Object metadata는 strict mock 증거로 남고 Docker 또는 Podman object는 label을 저장하거나 강제하지 않습니다. Bounded clock-skew 계약, multi-host lock 또는 authority, database service, power-loss 자격 검증, 제품 adapter 통합도 없습니다.

다음 ownership 경계는 공통 authority를 노출하고 object label 계약을 구현하며 재사용 가능한 suite 2개를 변경 없이 통과하고 in-flight 취소 또는 안전한 수렴의 명시적인 native platform 증거를 만드는 검토된 Docker 또는 Podman adapter입니다. [Owner lease, liveness, runtime fencing](owner-lease-runtime-fencing.md), [native object runtime fencing conformance](native-runtime-fence-conformance.md), [durable runtime fence authority 및 활성화 복구](durable-runtime-fence-authority.md)를 참고합니다. 제품 작업은 불변 engine profile, M1 증거, 제품 adapter 검토, 기존 no-socket 제품 경계에 따라 계속 gate 상태입니다.
