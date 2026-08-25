# M2 native object runtime fencing conformance

[English](../../en/m2/native-runtime-fence-conformance.md) | [M2 상태](README.md)

- 상태: 엔진 독립 후보 계약 test 완료, 제품 비활성
- 기준 runtime: strict memory 기반 mock만 사용
- 제품 Docker 및 Podman adapter: 미구현

## 계약 경계

`RuntimeFenceAuthority`는 모든 job-bound runtime operation 전후에 확인하는 adapter 독립 권한 경계입니다. 제공되는 `InMemoryRuntimeFenceAuthority`는 conformance test를 위한 공유형 process-local 기준 구현입니다. Canonical job UUID마다 활성화된 가장 높은 owner generation을 기록합니다. 더 낮은 token, 활성화되지 않은 token, 같은 token과 다른 owner의 조합은 stable `operation-fenced`로 실패합니다.

각 bound 호출은 adapter operation에 진입하기 직전에 `RuntimeFencingContext`를 활성화하고 operation이 반환된 직후 같은 context를 다시 확인합니다. 두 번째 검사는 이전 native 요청이 진행 중일 때 더 새로운 owner가 활성화되면 stale 성공 결과가 호출자에게 전달되는 것을 막습니다.

이 authority는 process 사이에서 durable하지 않습니다. Durable store commit과 runtime 활성화도 하나의 원자적 동작이 아닙니다.

## Managed object metadata

Bound mock adapter가 생성한 모든 managed volume과 container는 다음 metadata label을 정확히 저장합니다.

| Label | 필수 값 |
|---|---|
| `tcad.job_id` | Canonical job UUID |
| `tcad.owner_id` | Canonical owner UUID |
| `tcad.fencing_token` | Canonical 양의 10진 정수 |

`RuntimeFencingContext.from_labels()`는 관찰된 generation을 복원하며 필수 label 누락, text가 아닌 값, canonical 형식이 아닌 UUID, 앞자리 0, 0 이하 token을 실패 폐쇄합니다. 관련 없는 다른 runtime label은 함께 존재할 수 있습니다. `RuntimeJobBackend.inspect_fence()`는 job-bound managed handle에서 정규화된 fencing context만 노출합니다.

## Object 권한 규칙

일반 lifecycle 작업은 요청 generation과 object에 저장된 generation이 정확히 일치해야 합니다. Input staging, container 생성, start, wait, artifact 수집에 적용됩니다. 현재의 더 높은 generation은 cancellation과 recovery가 이전 object를 수렴시킬 수 있도록 이전 generation object에 `query`, `kill`, `cleanup`만 수행할 수 있습니다. 같은 token의 owner 불일치, 관찰된 더 높은 token, 모든 cross-job 사용은 실패 폐쇄합니다.

Adapter는 object 생성 시점뿐 아니라 모든 operation에서 object label을 검사합니다. Authority 검사와 object label 검사는 별도 요구 사항입니다. 첫 번째 검사는 현재 요청자를 정하고 두 번째 검사는 native object를 소유한 generation을 정합니다.

## 재사용 가능한 증거

`RuntimeFenceConformanceMixin`은 향후 adapter가 변경하지 않고 실행해야 하는 공통 case 5개를 정의합니다.

1. Volume 및 container의 정확한 label 저장과 정규화 inspection
2. Authority 하나를 공유하는 adapter instance 2개 사이의 fencing
3. 같은 token과 다른 owner 조합 거부
4. Takeover 때 이전 object 접근을 query, kill, cleanup으로 제한
5. Cross-job object inspection 및 변경 거부

집중 test 3개는 잘못된 label과 활성화 전 verification을 추가로 거부합니다. 또한 이전 mock wait가 native state를 변경한 뒤 결과를 반환하기 전 결정론적으로 takeover를 배치합니다. 이전 호출자는 `operation-fenced`를 받고 현재 owner는 이전 container와 volume을 제거한 뒤 managed object가 0인지 다시 확인합니다.

마지막 case는 stale 결과 차단과 안전한 cleanup 수렴을 증명합니다. 제출된 native 호출이 취소됐거나 해당 변경이 rollback됐음을 증명하지는 않습니다.

## 제품 게이트

향후 Docker 또는 Podman adapter는 같은 authority, label 저장, 정규화 inspection, operation별 object 강제, operation 전 활성화, operation 후 verification을 구현하고 공통 suite를 변경 없이 통과해야 합니다. 제품 승격에는 승인된 불변 engine profile, 승인된 M2 진입 문서, native platform 장애 증거, process 간 durable authority 설계, 명시적인 in-flight 취소 또는 수렴 증거도 필요합니다. 이 작업은 runtime socket을 열지 않으며 제품 실행 권한을 부여하지 않습니다.
