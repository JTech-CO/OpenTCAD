# OpenTCAD

[English](README.md) · [공개 미리보기](https://jtech-co.github.io/OpenTCAD/) · [아키텍처](docs/ko/architecture.md) · [개발](docs/ko/development.md)

![OpenTCAD 소셜 미리보기](frontend/public/og.png)

OpenTCAD은 반도체 공정과 소자 시뮬레이션 개념을 학습하기 위한 오픈 소스 한·영 작업공간입니다. 설명용 SUPREM 형식 공정 흐름, 소자 구조, 바이어스 조건, I–V 동작을 하나의 반응형 웹 경험으로 연결합니다.

공개 화면은 영어로 시작합니다. 언제든지 **한국어**를 선택해 소개 페이지와 작업공간을 한국어로 전환할 수 있습니다.

> OpenTCAD은 교육, 인터페이스 탐색, 수치 실험용입니다. 반도체 제조 공정의 sign-off 도구가 아닙니다.

## 현재 릴리스

GitHub Pages에 공개된 빌드는 안전한 정적 제품 미리보기입니다. 다음 항목을 제공합니다.

- 영어 기본 소개 페이지와 저장되는 한국어 선택 기능
- 공정, 소자, 곡선 비교, 런타임 경계 화면
- 메모리에서만 편집하는 예제 입력과 결정론적 과학 시각화
- 명시적인 출처 정보와 `솔버 출력 아님` 표시
- 반응형 레이아웃, 키보드 포커스 표시, 자동 UI 테스트
- Python 계약 테스트가 있는 런타임 중립 브로커, 취소, 복구, fencing, SQLite 내구성, 인증 백업 후보
- GitHub Pages 하위 경로와 일반 로컬 웹 서버에서 동작하는 정적 산출물

이 빌드는 제출한 입력, 컨테이너, SUPREM-IV.GS, Gmsh 또는 DEVSIM을 **실행하지 않습니다**. 백엔드 코드는 제품에서 비활성화된 계약과 영속성 기반이며 연결된 솔버 서비스가 아닙니다. 이 저장소는 제3자 솔버 소스나 바이너리를 배포하지 않습니다.

## 웹 앱 둘러보기

[공개 미리보기](https://jtech-co.github.io/OpenTCAD/)를 열거나 로컬에서 실행합니다.

요구사항:

- Node.js 22 LTS 또는 24 LTS
- npm 10 이상

```bash
npm install
npm run dev
```

Vite가 출력한 loopback 주소를 엽니다. 소개 페이지가 기본 화면이며 `#workspace`를 사용하면 참조 작업공간을 바로 열 수 있습니다.

배포 빌드를 검사하고 미리 보려면 다음 명령을 실행합니다.

```bash
npm run check
npm run preview
```

배포 산출물은 `frontend/dist/`에 생성됩니다. 미리보기 서버는 `127.0.0.1`에 바인딩됩니다.

## 제품 경계

| 화면 또는 구성요소 | 제공 여부 | 솔버 입력 실행 |
|---|---:|---:|
| GitHub Pages 소개 페이지와 작업공간 | 제공 | 실행 안 함 |
| 로컬 정적 개발·미리보기 서버 | 제공 | 실행 안 함 |
| 런타임 계약과 영속 상태 후보 | 테스트 전용 | 실행 안 함 |
| 연결된 Docker 또는 Podman 솔버 서비스 | 미제공 | 실행 안 함 |

화면의 모든 프로파일, 단면, I–V 곡선은 결정론적 참조 데이터입니다. 검증 결과로 내보낼 수 없으며 수렴한 솔버 출력으로 제시하지 않습니다.

## 저장소 구성

```text
frontend/              React 소개 페이지와 정적 참조 작업공간
backend/app/runtime/   런타임 프로토콜, 정책, identity, fencing 계약
backend/app/broker/    영속 상태, lifecycle, recovery, archive, backup 후보
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

전체 검사는 한국어 문장부호, 계약 기록, 프런트엔드 lint와 테스트, Python 런타임 테스트, 검증 테스트, 정적 배포 빌드를 실행합니다. 백엔드 테스트에는 Python 3.12부터 3.14가 필요합니다. 공개 정적 앱에는 Docker가 필요하지 않습니다.

## 문서

| English | 한국어 |
|---|---|
| [Architecture](docs/en/architecture.md) | [아키텍처](docs/ko/architecture.md) |
| [Development](docs/en/development.md) | [개발](docs/ko/development.md) |
| [Licensing](docs/en/licensing.md) | [라이선스](docs/ko/licensing.md) |
| [Implementation scope and comparison](docs/en/implementation-scope.md) | [구현 범위와 비교](docs/ko/implementation-scope.md) |
| [Validation](validation/README.md) | [검증](validation/README.ko.md) |

## 라이선스

OpenTCAD 고유 애플리케이션 코드와 문서는 [MIT 라이선스](LICENSE)로 배포합니다. 이 라이선스는 SUPREM-IV.GS, Gmsh, DEVSIM, 관련 예제 또는 다른 업스트림 자료에 적용되지 않습니다. 배포 경계는 [라이선스 문서](docs/ko/licensing.md), [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md), [NOTICE](NOTICE)에서 확인할 수 있습니다.

Copyright © 2026 JTech-CO.
