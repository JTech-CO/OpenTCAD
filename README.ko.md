# OpenTCAD

[English](README.md) · [공개 미리보기](https://jtech-co.github.io/OpenTCAD/) · [아키텍처](docs/ko/architecture.md) · [로컬 서비스](docs/ko/m3-local-service.md)

![OpenTCAD 소셜 미리보기](frontend/public/og.png)

OpenTCAD은 일반 컴퓨터에서 사용하는 오픈 소스 한영 반도체 공정·소자 시뮬레이션 작업공간입니다. 즉시 해석식 계산, 선택형 로컬 솔버 실행과 참조 UI를 제공합니다. 재현 가능한 연구·자동화 플랫폼을 지향하며 초기 전용 로컬 MCP 연결기를 구현했습니다. 더 넓은 연구 기능은 계속 개발 중입니다.

[제품 및 릴리스 범위](docs/ko/product-scope.md)를 참고하세요. 전용 시험장비나 기관 자격 검증은 일반 소프트웨어 출시의 전제 조건이 아닙니다. 수치 검증과 소프트웨어 복구 시험은 유지합니다.

공개 화면은 영어로 시작합니다. 언제든지 **한국어**를 선택해 소개 페이지와 작업공간을 한국어로 전환할 수 있습니다.

> OpenTCAD은 교육, 인터페이스 탐색, 수치 실험용입니다. 반도체 제조 공정의 sign-off 도구가 아닙니다.

## 현재 릴리스

이 소스에는 실제 동작하는 교육용 소자 실험실과 별도의 참조 작업공간이 있습니다. 공개 미리보기는 배포된 `main` 리비전을 따르므로 개발 브랜치의 변경이 아직 반영되지 않았을 수 있습니다. 다음 기능을 제공합니다.

- 영어 기본 소개 페이지와 저장되는 한국어 선택 기능
- 파라미터를 바꾸면 즉시 계산하는 장채널 NMOS 계산기
- I-V·공간 분포 결과, 취소, 수치 검사, 파일 재실행을 지원하는 선택형 로컬 DEVSIM 2.11.0 PN 접합 솔버
- 치수·바이어스 편집, 삼각형 메시의 전위·캐리어·도핑 지도, 드레인 I-V 곡선을 제공하는 실제 DEVSIM 2D MOSFET 템플릿
- 실험용 SUPREM 활성 도핑 가져오기와 고정 덱 공정 CLI, 실제 Podman SUPREM부터 2D DEVSIM까지의 연계 관측
- 파일 해시에 묶인 명시적 전극 경계, 형상 검사와 재실행을 지원하는 SUPREM 원본 실리콘·산화막 메시 전달
- 로컬 이력 재열기, 저장된 PN·2D 결과 표시, 출처를 확인하는 최종 전류 비교와 결과 내보내기
- 기본 읽기 전용 [로컬 stdio MCP](docs/ko/mcp.md), 선택형 실행·취소와 실행 없는 제한된 스윕 계획
- 공정, 소자, 곡선 비교, 런타임 경계 화면
- 프로젝트 파일 저장·가져오기, 설명용 덱 진단, 바이어스 편집, 결정론적 참조 시각화
- 재료·전극 선택, 단면 확대·이동, 읽기 전용 JSON/CSV 결과 가져오기와 비교
- 모의 동작임을 명시한 실행·취소·중단 복구 워크플로
- 명시적인 출처 정보와 `솔버 출력 아님` 표시
- 반응형 레이아웃, 키보드 포커스 표시, 자동 UI 테스트
- Python 계약 테스트가 있는 Docker 및 Podman 어댑터, durable fencing, 인증 loopback 서비스, OS 자격 증명 어댑터, lifecycle 통합, 예약 backup 코드
- GitHub Pages 하위 경로와 일반 로컬 웹 서버에서 동작하는 정적 산출물

정적 빌드는 해석식 계산을 수행하며 네이티브 솔버를 실행하지 않습니다. 명시적으로 켜는 실험용 로컬 서비스는 별도 설치한 DEVSIM으로 고정 템플릿을 실행하고 임의 코드나 공정 덱은 받지 않습니다. M3 제품은 실패 폐쇄 상태이며 런타임·전원 차단·솔버 릴리스 승인 상태는 그대로입니다. 저장소는 제3자 솔버 소스나 바이너리를 배포하지 않습니다. 아직 SUPREM부터 DEVSIM까지 연결하는 전체 공정·소자 제품은 아닙니다.

## 소자 실험실 실행

Windows에서 작업 기록 저장과 오프라인 백업·복원을 사용하려면 별도의
[Windows 로컬 MVP 후보](docs/ko/windows-mvp.md)를 이용합니다. M3, 물리적 전원 차단
내구성이나 다른 운영체제의 승인을 뜻하지 않습니다.

```bash
npm run local:mvp -- doctor
npm run local:mvp -- serve
```

Windows·macOS·Linux 설치, 물리적 가정, 한계, 재현 절차는 [MVP 실험실 안내](docs/ko/mvp-laboratory.md)를 확인하세요. 브라우저 계산기는 `npm ci`, `npm run dev`로 시작합니다. 버전 고정된 실험용 Python 의존성을 설치한 뒤에는 다음과 같이 실행합니다.

```bash
npm run build
npm run test:mvp:solver
npm run local:lab
```

`local:lab`이 출력한 개인용 주소를 엽니다. 접근 토큰을 공유하지 마세요. 이 선택형 모드는 M3 승인이 필요한 `local:serve`와 별개입니다.

지원 형상, 공정 CLI, 구조 전달, 수치 검사와 남은 제한은 [2D MOSFET·SUPREM 연계 안내](docs/ko/mos-process.md)를 확인하세요.
기본 소자 메시로 도핑을 보간하지 않고 공정 삼각형을 유지하려면 [원본 공정 메시 안내](docs/ko/process-mesh.md)를 확인하세요.

## 웹 앱 둘러보기

파일 형식, 예제, 비교 규칙, 키보드 조작, M3에 의존하여 유보된 작업은
[M4 작업공간 안내](docs/ko/m4-workspace.md)에서 확인합니다.

[공개 미리보기](https://jtech-co.github.io/OpenTCAD/)를 열거나 로컬에서 실행합니다.

요구사항:

- Node.js 22 LTS 또는 24 LTS
- npm 10 이상

```bash
npm install
npm run dev
```

Vite가 출력한 loopback 주소를 엽니다. 소개 페이지가 기본 화면이며 주 실행 버튼은 `#lab`으로 연결합니다. `#workspace`를 사용하면 별도의 참조 작업공간을 바로 열 수 있습니다.

배포 빌드를 검사하고 미리 보려면 다음 명령을 실행합니다.

```bash
npm run check
npm run preview
```

배포 산출물은 `frontend/dist/`에 생성됩니다. 미리보기 서버는 `127.0.0.1`에 바인딩됩니다.

M3 상태를 확인하고 동일 출처 방식의 비실행 로컬 미리보기를 시작할 수 있습니다.

```bash
npm run local:doctor
npm run local:preview
```

미리보기 명령은 수명이 짧은 민감한 `browserUrl`을 출력합니다. 브로커 상태를 만들지 않고 OS 자격 증명을 읽지 않으며 컨테이너 런타임에 접근하지 않습니다. 제품 명령, 설정 경로, 시작 순서, 현재 활성화 차단 항목은 [M3 로컬 제품 서비스](docs/ko/m3-local-service.md)에서 확인할 수 있습니다.

## 제품 경계

| 화면 또는 구성요소 | 제공 여부 | 솔버 입력 실행 |
|---|---:|---:|
| GitHub Pages 소개 페이지와 작업공간 | 제공 | 실행 안 함 |
| 로컬 정적 개발·미리보기 서버 | 제공 | 실행 안 함 |
| 동일 출처 차단형 로컬 제품 미리보기 | 제공 | 실행 안 함 |
| 선택형 실험용 로컬 DEVSIM 실험실 | 별도 솔버 설치 후 제공 | 고정 PN 템플릿만 실행 |
| 런타임 계약과 durable 로컬 서비스 | 구현됨, 게이트로 비활성 | 실행 안 함 |
| 연결된 Docker 또는 Podman solver 서비스 | 외부 증거 대기 | 실행 안 함 |

참조 작업공간은 설명용입니다. 실험실은 해석식 계산과 실제 DEVSIM 결과를 구분합니다. 제한된 수치 검사는 M3 corpus 승인이나 제조 공정 sign-off가 아닙니다.

## 저장소 구성

```text
frontend/              React 소개 페이지와 정적 참조 작업공간
backend/app/product/   증거 기반 제품 활성화와 정확한 runtime grant
backend/app/runtime/   런타임 프로토콜, 정책, identity, fencing 계약
backend/app/broker/    영속 상태, lifecycle, recovery, archive, backup 후보
backend/app/service/   인증 loopback API, worker, credentials, scheduler, 제품 assembly
backend/tests/         의존성 없는 Python 계약 및 crash recovery 테스트
validation/            외부 관찰 도구, schema, comparator
docs/en/               관리되는 영어 엔지니어링 문서
docs/ko/               관리되는 한국어 엔지니어링 문서
.github/workflows/     CI 및 GitHub Pages 배포
```

## 품질 검사

```bash
npm run check
npm run coverage
```

전체 검사는 한국어 문장부호, M0부터 M3까지의 계약 기록, 프런트엔드 lint와 테스트, Python 런타임 테스트, 검증 테스트, 정적 배포 빌드를 실행합니다. 백엔드 테스트에는 Python 3.12부터 3.14가 필요합니다. 공개 정적 앱에는 Docker가 필요하지 않습니다.

## 문서

| English | 한국어 |
|---|---|
| [Architecture](docs/en/architecture.md) | [아키텍처](docs/ko/architecture.md) |
| [Development](docs/en/development.md) | [개발](docs/ko/development.md) |
| [Licensing](docs/en/licensing.md) | [라이선스](docs/ko/licensing.md) |
| [Implementation scope and comparison](docs/en/implementation-scope.md) | [구현 범위와 비교](docs/ko/implementation-scope.md) |
| [M3 product entry gates](docs/en/m3-entry-gates.md) | [M3 제품 진입 게이트](docs/ko/m3-entry-gates.md) |
| [M3 local product service](docs/en/m3-local-service.md) | [M3 로컬 제품 서비스](docs/ko/m3-local-service.md) |
| [Validation](validation/README.md) | [검증](validation/README.ko.md) |

## 라이선스

OpenTCAD 고유 애플리케이션 코드와 문서는 [MIT 라이선스](LICENSE)로 배포합니다. 이 라이선스는 SUPREM-IV.GS, Gmsh, DEVSIM, 관련 예제 또는 다른 업스트림 자료에 적용되지 않습니다. 배포 경계는 [라이선스 문서](docs/ko/licensing.md), [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md), [NOTICE](NOTICE)에서 확인할 수 있습니다.

Copyright © 2026 JTech-CO.
