# M0 기준선 고정 및 clean-room 정책

[English](../../en/m0/baseline-and-clean-room.md) | [M0 상태](README.md)

## 고정 참조

| 참조 | Commit | 허용 용도 |
|---|---|---|
| `ypooh2042/tcad-webapp` | `13bce4a9daba5796ceee633fb8cd0c870465f766` | 읽기 전용 동작, 아키텍처, 의존성, 라이선스 증거 |
| OpenTCAD 기반 | `4a7cae9b5192e52730f204b1236ff63a1abe3988` | 처음 병합한 한·영 정적 기반 |
| OpenTCAD M0 부모 | `f0305c8d4f79b8c8aea7683d52fd17bb61342001` | M0 조사 변경의 부모 commit |

기계 판독 기록은 [`m0/BASELINE_FREEZE.json`](../../../m0/BASELINE_FREEZE.json)에 있습니다. 이동하는 branch나 가변 이미지 tag는 이 기준선을 바꾸지 않습니다.

## 검증된 범위

OpenTCAD 정적 기반은 빌드되고 결정론적 UI test 9개를 통과하며 알려진 npm audit 문제가 없고 GitHub Pages에 배포됩니다. 공정 profile과 I-V curve는 참조 미리보기 데이터로 표시됩니다. 이 증거는 UI 기반만 검증합니다.

OpenTCAD에서 SUPREM 또는 DEVSIM 수치 결과를 검증한 적은 없습니다. Linux 참조 실행, 골든 case 3종, 반복 실행 분산, 불변 솔버 이미지 digest, 장애 경로 관찰은 대기 상태입니다.

## 필수 실행 증거

각 기준선 실행은 다음을 기록해야 합니다.

- 저장소 commit, host OS와 architecture, runtime version, 불변 이미지 digest
- 입력 byte와 SHA-256
- command contract, environment allowlist, resource limit, 종료 분류
- 출력, 로그, 이미지, metric hash
- 적용 가능한 node, element, region, contact, artifact size count
- 공정 metric, 소자 curve metric, 수렴 의미
- 반복 실행 분포, cancellation, timeout, output limit, restart 동작

종료 코드 0은 수치 성공이 아닙니다. Screenshot은 골든 결과가 아닙니다. 원본 산출물과 기계 판독 metric이 기준입니다.

## Clean-room 경계

OpenTCAD은 참조 애플리케이션 코드, 문장, asset, 내부 구성을 복사하지 않고 관찰 가능한 동작과 문서화된 상호운용 계약을 재현해야 합니다.

허용 입력은 다음과 같습니다.

- UI 또는 문서화된 API를 통해 관찰한 공개 제품 동작
- 독립적으로 작성한 요구사항, test case, schema, 수치 불변식
- 호환성에 필요한 공개 솔버 format과 interface
- 검토에 필요한 라이선스, provenance, 의존성, 보안 사실

금지 입력은 다음과 같습니다.

- 참조 애플리케이션 source, comment, documentation, UI 문구의 복사 또는 번역
- 호환성에 필요하지 않은 내부 이름, 파일 구조, control flow, data structure의 기계적 보존
- 명시적 권리 없이 참조 screenshot 또는 asset 반입
- 제3자 솔버 코드나 패치를 MIT 소유권 경계 안에 배치

솔버 기반 작업은 관찰·명세 역할과 구현 역할을 분리하는 흐름을 우선합니다. 관찰자는 외부에서 시험할 수 있는 동작과 필수 interface만 기록합니다. 구현자는 그 명세와 OpenTCAD test를 바탕으로 작성합니다. 참조 내부를 확인한 기여자는 검토 기록에 접근 사실을 밝혀야 합니다.

이 정책은 M0 이후 작업을 통제합니다. 정책 자체가 어떤 작업을 법률상 정식 clean-room 구현으로 인증하지는 않습니다.

## M0 소스 접근 기록

2026-08-23 M0 인벤토리 검토에서 고정 참조본의 SUPREM 라이선스와 provenance, backend 의존성 선언, Compose 서비스 정의, Containerfile 3개를 읽었습니다. 목적은 라이선스, 의존성, 이미지, sandbox, 아키텍처 특성 기록이었습니다. 참조 애플리케이션 source는 OpenTCAD에 복사하지 않았습니다.

2026-08-24 BASE-001 관찰자는 공개 1D boron example deck도 읽고 생성 structure를 고정 test fixture Git blob과 hash로만 비교했습니다. 관찰자는 외부 고정 tree를 로컬에서 build하고 실행했으며 외부에서 보이는 log를 확인하고 정규화한 사실만 기록했습니다. 원본 source, patch, binary, image, log, structure, plot, SBOM은 OpenTCAD 밖에 유지합니다. 두 번째 rootless Podman 관찰은 같은 고정 입력을 사용하고 profile 검사, hash, count, log finding, 로컬 image identity만 기록했으며 Podman image archive나 SBOM을 OpenTCAD에 반입하지 않았습니다. 관찰 하네스는 OpenTCAD 증거 요구사항을 바탕으로 독립 작성했으며 참조 애플리케이션의 control flow나 구성을 재현하지 않습니다.
