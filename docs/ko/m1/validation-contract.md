# M1 검증 계약

[English](../../en/m1/validation-contract.md) | [M1 상태](README.md)

## 코퍼스 수명주기

Case는 다음 두 상태로만 이동합니다.

1. `pending-m0`: 목표 coverage를 설명하지만 fixture path, input hash, baseline identifier, expected value, 승인 engine이 없습니다.
2. `frozen`: 사용 권한이 확인된 input byte, 불변 engine identity, 원본 artifact, metric, 반복 실행 증거, warning policy, 검토 승인을 모두 기록합니다.

CI는 이 상태 전환을 수행할 수 없고 golden artifact를 쓸 수 없습니다. 실패한 test를 같은 변경에서 expected value 교체로 해결하지 않습니다.

## Comparator 의미

| Comparator | 계약 |
|---|---|
| `exact-hash` | SHA-256과 byte length가 정확히 일치해야 함 |
| `topology` | Node, element, region, contact count는 정확히 비교하고 material, region, contact name은 중복 없는 set으로 비교 |
| `scalar` | 값은 finite이어야 하며 `abs(actual - expected) <= max(absTolerance, relTolerance * scale)`을 통과해야 함 |
| `curve` | Point count, ordering, x coordinate, y coordinate, solve status를 독립 검사하며 skipped point는 기본 실패 |
| `repeatability` | Finite sample이 5개 이상이어야 하며 관찰 range가 검토된 absolute 또는 relative range gate 안에 있어야 함 |

`scale`은 expected와 actual scalar의 절댓값 중 큰 값입니다. NaN과 infinity는 변환하거나 무시하지 않고 오류로 처리합니다.

## 허용오차 관리

- 검토된 manifest가 음수가 아닌 값을 제공하지 않으면 tolerance는 0입니다.
- Absolute 및 relative tolerance는 단위와 근거를 포함해 frozen baseline에 별도로 기록합니다.
- 하나의 porting 변경에서 engine version, physical model, convergence policy, tolerance를 함께 변경하지 않습니다.
- Tolerance를 선정하기 전에 자연 분산을 측정합니다.
- Non-converged, skipped, missing, reordered curve point를 comparator interpolation으로 보정하지 않습니다.

## Topology 및 curve negative control

Unit test는 topology count 하나를 바꾸고, curve point를 skip하고, curve 길이를 줄이고, curve tolerance를 초과시킵니다. 이는 framework control일 뿐입니다. M1 종료 전 실제 frozen TCAD fixture를 사용한 negative control이 추가로 필요합니다.

## Report

`buildValidationReport`는 호출자가 timestamp, baseline identifier, case identifier, metadata, comparator result를 제공할 때 결정론적 JSON을 만듭니다. `renderValidationReportHtml`은 script나 외부 asset 없이 같은 object를 표시합니다. JSON object가 권위 있는 결과이며 HTML은 검토 화면입니다.

솔버 기반 report에는 불변 repository, input, engine, image, architecture, raw artifact, metric identity가 필요합니다. 현재 report schema는 공통 envelope만 정의하고 값을 만들어 넣지 않습니다.

## Image lock

Image lock은 M0 이미지 참조 6개를 반영하여 drift를 드러냅니다. Digest, architecture, SBOM hash, approval은 모두 비어 있습니다. 정확한 manifest digest, 지원 platform, SBOM, license review, reproducible build evidence를 함께 기록해야 격리를 해제할 수 있습니다.
