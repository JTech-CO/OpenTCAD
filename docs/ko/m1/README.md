# M1 재현성 및 검증 상태

[English](../../en/m1/README.md)

M1은 `gated-active` 상태입니다. OpenTCAD은 엔진 독립 검증 계약을 구현하지만, M0에 사용 권한이 확인된 불변 솔버 이미지, 고정 예제 metric, 승인된 source development 라이선스 범위가 없으므로 M1 진입 게이트는 충족되지 않았습니다.

이번 M1 기반에 포함된 파일은 수치 기준선이나 솔버 결과가 아닙니다.

## 작업 현황

| 작업 | 상태 | 현재 결과 |
|---|---|---|
| BASE-002 공정 코퍼스 | 후보 manifest | 공정 case 5개를 선언했으며 source와 expected value는 없음 |
| BASE-003 `.str` topology 코퍼스 | 후보 manifest | 필수 topology field를 선언했으며 fixture는 격리 상태 |
| BASE-004 DEVSIM I-V 코퍼스 | 후보 manifest | 소자 case 4개를 선언했으며 curve와 metric은 비어 있음 |
| BASE-005 comparator 및 report | 기반 구현 | Exact hash, topology, scalar, curve, repeatability, JSON, HTML 계약과 unit test 구현 |
| BASE-006 PR CI | 기반 확장 | 저장소, M0, M1, 문장부호, lint, test, build gate를 CI에서 실행 |
| BASE-001 외부 관찰 | 하네스 구현, 실행 결과 ineligible | Rootless Podman이 Docker structure 출력 5회와 일치하고 통제 image 재빌드도 정확하지만 log, 권리, corpus, SBOM 검토, 승인 게이트로 승격 차단 |
| 재현 가능 image lock | 통제 관찰, release lock 격리 | Digest, snapshot, timestamp를 고정한 Podman image가 정확히 재빌드되고 외부 미검토 SBOM도 있으나 release 승인 solver image는 없음 |
| M0 장애 경로 기반 | 엔진 독립 계약 test 완료 | 실제 자식 프로세스로 timeout, 취소, 출력 상한, worker 초기화를 검사했으나 OCI 및 solver 증거는 대기 상태 |
| M1 종료 | 미충족 | Linux 기준선, 5회 반복 분산, numerical PR smoke가 대기 상태 |

## 산출물

- [검증 계약](validation-contract.md)
- [BASE-001 외부 관찰](../m0/base001-reference-observation.md)
- [참조 관찰 계획](../../../validation/plans/base001-process-1d-boron.json)
- [참조 관찰 test](../../../validation/baseline/observation.test.mjs)
- [장애 경로 계약](../m0/fault-path-foundation.md)
- [장애 경로 supervisor test](../../../validation/faults/supervisor.test.mjs)
- [후보 코퍼스](../../../validation/corpus/index.json)
- [M1 기반 manifest](../../../validation/manifests/m1-foundation.json)
- [Image lock 격리 기록](../../../validation/manifests/image-lock.json)
- [Corpus schema](../../../validation/schemas/corpus.schema.json)
- [Report schema](../../../validation/schemas/report.schema.json)
- [Comparator 구현](../../../validation/comparators/index.mjs)
- [Comparator test](../../../validation/comparators/comparators.test.mjs)

`npm run check:m1`은 근거 없는 expected value, 고정되지 않은 fixture path, 알 수 없는 comparator, 증거 없는 이미지 승인, M0 hash 변동, 자동 baseline update command를 거부합니다. `npm run test:validation`은 의도적인 topology, curve, repeatability 실패를 포함해 comparator 동작을 검증합니다.

## 다음 게이트

1. 적용되는 M0 라이선스 및 Linux 기준선 게이트를 완료하거나 명시적으로 결정합니다.
2. 독립 작성 또는 사용 권한이 확인된 fixture 입력을 선정하고 SHA-256을 고정합니다.
3. 통제 image와 SBOM 증거를 검토하고 권리 및 license conclusion이 허용할 때만 정확한 release identity를 승인합니다.
4. 같은 Linux 기준선에서 모든 후보를 5회 실행합니다.
5. 허용오차나 expected value를 정하기 전에 자연 분산을 검토합니다.
6. 검토된 기준선이 불변 상태가 된 후 numerical PR smoke를 추가합니다.

이 구현은 baseline을 자동으로 갱신하는 command를 의도적으로 제공하지 않습니다.
