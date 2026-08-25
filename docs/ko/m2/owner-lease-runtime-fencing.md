# M2 owner lease, liveness 및 runtime fencing

## 범위

이 작업은 비활성 mock 전용 durable composition을 확장합니다. Docker 또는 Podman 제품 adapter, runtime socket 접근, broker service, worker, solver 실행은 추가하지 않습니다. SQLite 후보와 strict mock runtime은 계속 제품 비활성 상태입니다.

## Durable owner lease

Commit된 각 owner generation에는 제한된 lease가 부여됩니다. 기본 기간은 30,000밀리초, 기본 heartbeat 간격은 10,000밀리초, 최대 기간은 300,000밀리초입니다. State adapter가 `now < lease_expires_at_ms`를 판정하는 UTC epoch-millisecond clock을 소유합니다.

변경되지 않는 `job_events` audit log는 요청된 lease 기간과 각 event commit 때 결정된 만료 시각을 기록합니다. Schema v3는 현재 owner, job revision, 만료 시각을 위한 별도의 `job_leases` control table을 추가합니다. `renew_ownership()`은 adapter transaction 안에서 정확히 일치하는 control row만 갱신합니다. Broker event를 만들거나 job revision을 증가시키지 않습니다.

갱신에는 정확한 job, operation, owner, fencing token, job revision이 필요합니다. 만료된 owner는 확인, 갱신, 다음 event append 또는 generation 부활을 할 수 없습니다. Cancellation은 명시적인 선점이므로 execution lease가 live 상태여도 다음 token으로 진행할 수 있습니다. Recovery는 이전 lease가 만료된 뒤에만 `cleaning`으로 진행할 수 있습니다. Recovery scan이 live generation을 관찰하면 `owner-active`를 보고하고 startup admission을 닫힌 상태로 유지합니다.

Guard가 적용된 모든 runtime await는 owner heartbeat로 감쌉니다. Guard는 호출 전, 호출이 대기 중일 때 주기적으로, 완료 후에 lease를 갱신합니다. 갱신 중 ownership을 잃거나 만료가 확인되면 Python awaitable을 취소하고 broker는 `operation-fenced`를 보고합니다.

## Runtime adapter fence

`RuntimeBackend.bind_job(RuntimeFencingContext)`는 broker가 사용하는 유일한 job lifecycle 진입점입니다. 이 메서드는 하나의 job UUID, owner UUID, 양의 fencing token에 바인딩된 `RuntimeJobBackend`를 반환합니다. Context는 향후 OCI metadata label인 `tcad.job_id`, `tcad.owner_id`, `tcad.fencing_token`을 제공합니다. `runtime_fencing`은 실패 폐쇄형 필수 runtime capability입니다.

Mock adapter는 `RuntimeFenceAuthority`를 주입받습니다. Process-local 기준 구현과 전용 SQLite process 간 후보는 모두 job별로 활성화된 가장 높은 generation을 보관합니다. `DurableRuntimeFenceActivator`는 정확한 live store owner 및 revision을 확인하고 같은 runtime context를 활성화한 다음 runtime 접촉 전에 두 경계를 다시 검사합니다. 모든 bound 호출도 adapter 작업 직전에 활성화하고 반환 직후에 다시 확인합니다. Managed mock volume과 container는 정확한 job, owner, token label을 저장하고 모든 operation은 관찰한 context를 복원해 검사합니다. 일반 lifecycle 작업에는 정확한 generation이 필요하고 더 높은 takeover는 이전 object에 query, kill, cleanup만 수행할 수 있습니다. 낮은 token, 같은 token의 owner 불일치, 잘못된 label, cross-job context, handle 불일치는 실패 폐쇄합니다.

Mock backend의 raw lifecycle 메서드는 바인딩되지 않은 test seed 전용 표면으로만 남습니다. 이 메서드는 `RuntimeBackend` 제품 protocol에 포함되지 않으며 broker의 job lifecycle에서 호출하지 않습니다.

## SQLite migration 및 recovery

Schema v3는 정확한 schema v1 및 v2 file을 forward-only `BEGIN IMMEDIATE` transaction으로 migration합니다. 기존 event와 owner generation은 보존됩니다. Legacy row의 만료 시각은 `1`이 되므로 migration된 owner는 보수적으로 expired 상태가 되고 다음 작업 전에 recovery claim이 필요합니다. 알 수 없거나 일치하지 않는 schema는 계속 실패 폐쇄합니다.

Memory 및 SQLite 공통 state-adapter conformance suite는 case 10개를 포함합니다. 재사용 가능한 runtime-fence suite는 label 저장, 공유 authority fencing, owner 불일치, takeover 제한, cross-job 거부를 위한 공통 adapter case 5개를 추가합니다. 집중 case 3개는 잘못된 label, 활성화 전 verification, post-mutation stale 결과 차단과 이후 current-owner cleanup 수렴을 검사합니다. 별도 lease 및 recovery test는 heartbeat renewal, 만료된 in-flight awaitable 취소, schema v2 migration, hard-exit takeover를 계속 검사합니다. Dependency-free backend suite는 test 133개를 포함합니다.

## 의도적으로 남긴 한계

이는 비활성 후보와 strict mock adapter를 위한 durable liveness, local process 간 authority, native object 계약 강제이며 제품 OCI adapter 또는 distributed system의 증거가 아닙니다. Store commit과 runtime 활성화는 하나의 원자적 동작이 아니며 authority database는 broker state와 분리됩니다. 제출된 native operation은 takeover 뒤에도 변경을 완료할 수 있습니다. Operation 후 검사는 stale 결과를 차단하고 current-owner cleanup은 수렴할 수 있지만 native 취소나 rollback을 증명하지는 않습니다. Mock object metadata도 Docker 또는 Podman metadata가 아닙니다.

System clock은 이동할 수 있고 독립적으로 설정된 host는 서로 다른 시간을 판단할 수 있습니다. Database service, multi-host authority 또는 lease, clock-skew bound, quorum, 제품 adapter 자격 검증, power-loss 자격 검증, backup 및 restore 증거는 없습니다. Local SQLite 후보와 활성화 gap 복구는 [durable runtime fence authority 및 활성화 복구](durable-runtime-fence-authority.md)에 있습니다. 향후 Docker 또는 Podman adapter는 같은 label, authority, inspection, operation 규칙을 구현하고 공통 suite 2개를 변경 없이 통과하며 native platform 장애 증거를 만들어야 이 gate를 승격할 수 있습니다.
