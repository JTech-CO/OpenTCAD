# OpenTCAD 구현 범위와 기존 사이트 비교

[English](../en/implementation-scope.md)

## 기준과 분석 방법

이 문서는 읽기 전용 동작 참고본 `ypooh2042/tcad-webapp@13bce4a`와 현재 OpenTCAD 저장소를 비교합니다. 참고본의 README, 코드맵, 프런트엔드와 백엔드 패키지, 컨테이너 정의, 배포 구조를 확인했습니다. 업스트림 애플리케이션 소스는 OpenTCAD에 복사하지 않았습니다.

기존 사이트는 Linux 중심의 실제 솔버 애플리케이션입니다. 현재 OpenTCAD은 clean-room 방식으로 만든 한·영 정적 제품에 실패 폐쇄 로컬 서비스와 OCI 런타임 구현을 더한 상태입니다. 아직 기존 사이트를 기능 단위로 대체하지는 못합니다. 현재 릴리스는 실제 솔버 실행을 의도적으로 제외하는 대신 배포 경계, 공개 접근성, 언어 지원, 영속 lifecycle 설계, 교차 플랫폼 host 통합을 개선했습니다.

## 구현 가능한 제공 방식

| 방식 | 가능성 | 솔버 실행 | 권장 범위 |
|---|---|---:|---|
| GitHub Pages 정적 미리보기 | 현재 완료 | 불가 | 제품 둘러보기, 용어, 결정론적 참조 시각화, 문서 |
| OCI 런타임을 사용하는 loopback 전용 로컬 서버 | 높음, 권장 | 라이선스·검증 게이트 이후 가능 | Windows, macOS, Linux의 주 제품 |
| 인증된 공유 서버 | 로컬 모드 이후 중상 | 가능 | 계정, 쿼터, 감사, 백업이 필요한 수업·연구실 배포 |
| 선택적 데스크톱 래퍼 | 중간, 선택 사항 | 동일한 로컬 서버를 통해 실행 | 별도 런타임이 아닌 로컬 스택 실행 편의 계층 |
| 브라우저 내부 WASM 솔버 | 권장하지 않음 | 이론상 일부 가능 | 레거시 SUPREM, 프로세스 격리, 파일 산출물, 라이선스에 부적합 |
| 호스트 OS별 네이티브 솔버 포팅 | 주 경로로서 가치 낮음 | 가능 | 비용이 크고 수치 차이가 생기기 쉬우므로 향후 연구 경로로만 유지 |

권장 방식은 검증된 Linux 솔버 환경을 OCI 컨테이너에 유지하고 호스트 차이를 launcher와 런타임 adapter에서 흡수하는 것입니다. Windows의 Docker Desktop, macOS의 Docker Desktop 또는 Podman Machine, Linux의 Docker 또는 rootless Podman이 같은 Linux 실행 계약을 제공할 수 있습니다.

## 목표 종단 간 구현

```text
브라우저
  -> loopback 전용 웹 게이트웨이
  -> 표준 library 기반 인증 로컬 API
  -> 상한이 있는 실행 및 control worker lane
  -> 영속 SQLite 상태, recovery, backup control
  -> 샌드박스 브로커
  -> Docker 또는 rootless Podman adapter
  -> 격리된 잡별 관리 볼륨
  -> SUPREM-IV.GS
  -> 구조 파서와 Gmsh 재메시
  -> DEVSIM
  -> 버전이 지정된 산출물, 지표, 경고, 출처 정보
```

브라우저와 API에는 OCI 런타임 소켓을 절대 전달하지 않습니다. 컨테이너는 브로커만 생성하며, 브로커는 raw 명령·경로·이미지 이름·마운트·환경 값 대신 타입과 allowlist로 검증된 명세만 받습니다. 로컬 모드가 완성된 뒤에도 GitHub Pages는 입력을 실행하지 않는 빌드로 유지합니다.

## 기능 비교

| 기능 | 기존 참고 사이트 | 현재 OpenTCAD | 구현 가능한 OpenTCAD 목표 |
|---|---|---|---|
| 공개 정적 접근 | 별도의 안전한 정적 제품 없음 | GitHub Pages에 완료 | 공개 제품 화면으로 유지 |
| 영어와 한국어 | 주로 한국어 | 관리 UI와 제품 문서에 완료 | 번역 키와 한·영 문서 쌍 동등성 유지 |
| 공정 덱 편집기 | 실제 작업공간 파일을 쓰는 Monaco 편집기 | 메모리 전용 설명용 덱 | 안전한 프로젝트 저장소와 Monaco 또는 동등 편집기 |
| 문법 카탈로그와 매뉴얼 | 자동완성, 파라미터 표, 매뉴얼·레퍼런스 패널 | 없음 | clean-room 카탈로그와 배포 가능한 문서 색인 |
| SUPREM 공정 실행 | Linux rootless Podman으로 실제 잡 실행 | 의도적으로 비활성 | 배포·기준선 승인 후 OCI adapter |
| 공정 결과 | `.str` 파싱, 깊이 프로파일, 2D 단면, 단계 탐색 | 결정론적 참조 프로파일과 단면 | 검증 파서, topology 검사, 지표, 출처 정보 |
| 소자 설정 | 전극 매핑, 전압원, sweep, 정식화 선택 | 설명용 접촉과 고정 바이어스 표시 | 검증과 revision을 포함한 타입 소자 계획 |
| DEVSIM 해석 | density와 quasi-Fermi 실제 해석 | 결정론적 참조 I–V 곡선군 | 고정 이미지, 수렴 의미, fallback 증거, 골든 비교 |
| 저장 결과 비교 | 저장한 해석의 겹쳐 보기와 삭제 | 참조 곡선만 제공 | 버전 결과 묶음, 비교, 내보내기, replay |
| 파일과 프로젝트 | 서버 파일시스템 작업공간과 파일 연산 | 영속 프로젝트 없음 | 이식 가능한 `.tcadproj`, 안전한 가져오기·내보내기, 백업·migration |
| 인증과 관리 | 세션 로그인, 초대, 접속 현황, 관리자 기능 | 없음 | 단일 사용자 로컬 모드에서는 제외하고 공유 모드에서 복원 |
| 잡 큐와 중단 | PostgreSQL 큐, 워커, 폴링, 콘솔, 중단 | 영속 typed lifecycle과 cancellation 계약, UI 제출 비활성 | 승인된 solver 요청과 진단 연결 |
| 런타임 지원 | rootless Podman과 특정 Linux 서버 전제 | 증거 게이트가 있는 Docker 및 Podman adapter, 제품 비활성 | 3개 host에서 정확한 릴리스 image 검증 |
| 패키징 | Python, Node, Redis, PostgreSQL, 이미지 3개, systemd, nginx | 정적 host, doctor, 차단형 preview, 실패 폐쇄 제품 명령 | 서명 및 자격 검증된 플랫폼 실행 패키지 |
| 라이선스 | 인식 가능한 루트 라이선스 없음, 솔버 번들 경계 불명확 | OpenTCAD 고유 작업은 GitHub 인식 MIT, 솔버 제외 | 구성요소별 고지, 소스 출처, 승인된 배포 프로필 |
| CI와 배포 | 단위·통합·E2E 구조, 특정 서버 배포 | 프런트엔드, Python 계약, host 계약, 문장부호, Pages, gate 검사 | 승인된 native runtime 및 수치 릴리스 matrix 추가 |

## OpenTCAD에서 업데이트된 점

### 이미 제공하는 개선

- 입력을 실행하지 않는 공개 GitHub Pages 제품 화면
- OpenTCAD 고유 코드와 문서에 대한 명시적인 MIT 경계
- 영어·한국어 UI와 한·영 제품·엔지니어링 문서
- 솔버 출력이 아니라는 표시가 있는 결정론적 참조 시각화
- 반응형 공정·소자·비교·런타임 경계 경험
- 도메인 잡과 Docker·Podman 세부사항을 분리하는 교차 플랫폼 목표
- 상태를 만들지 않는 동일 출처 로컬 미리보기와 전송 연결 및 solver 권한의 분리 표시
- 증거 게이트 기반 Docker 및 Podman adapter, native fencing, 영속 SQLite lifecycle, recovery, maintenance, 인증 archive, 예약 backup 통합
- 엄격한 사용자별 경로와 운영자 설정을 사용하는 교차 플랫폼 `doctor`, 차단형 `preview`, 실패 폐쇄 `serve` 명령
- 최신 GitHub Actions, 잠긴 JavaScript 의존성, 자동 테스트, 소셜 미리보기

### 아직 복원하지 않은 기존 기능

- 실제 SUPREM 실행, `.str` 파싱, Gmsh 재메시, DEVSIM 해석
- Monaco 언어 통합, 서버 파일, 탭, 매뉴얼 패널, 파라미터 카탈로그
- 소자 계획 편집, 저장 해석, 곡선 겹치기, 사용자용 잡 중단, 로그, 산출물 다운로드
- 향후 공유 서버 모드의 인증, 초대, 관리
- 승인된 native runtime 관측, 실제 전원 차단 실행, 코드 소유 solver 릴리스 프로필, 플랫폼 package, upgrade UI

이 누락은 의도적입니다. 기존 소스를 복사하면 clean MIT 경계가 무너지고, 불완전하게 격리된 솔버 경로를 배포하면 현재 코드가 보장할 수 없는 보안 주장을 하게 됩니다.

## 현재 릴리스 경계

현재 공개 릴리스는 입력을 실행하지 않는 한·영 제품 미리보기로 완료되었습니다. M3는 실행 가능한 차단형 로컬 미리보기와 side effect 전에 활성화를 거부하는 제품 host도 제공합니다. 실제 솔버 실행은 이 릴리스에 포함되지 않으며 런타임 구현이나 결정론적 시각화에서 솔버 실행을 추론해서는 안 됩니다. 활성화에는 별도의 license, sandbox, 수치, data safety, 실제 전원 차단, 교차 플랫폼 승인이 필요합니다.

## 한국어 문장부호 정책

한국어 소유 문서에서는 유니코드 em dash 문자 `U+2014`를 사용하지 않습니다. 뜻에 따라 콜론, 쉼표, 괄호, ASCII 하이픈 또는 `해당 없음`과 같은 명시적 표현을 사용합니다. `I–V`, `Id–Vd`처럼 과학적 관계를 나타내는 en dash는 유지합니다. 영어 문장에는 정상적인 영어 em dash를 사용할 수 있습니다.
