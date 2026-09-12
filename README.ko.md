# OpenTCAD

[English](README.md) · [OpenTCAD 사용하기](https://jtech-co.github.io/OpenTCAD/) · [문서](docs/README.ko.md)

![OpenTCAD 소셜 미리보기](frontend/public/og.png)

OpenTCAD은 영어와 한국어 웹 인터페이스를 제공하는 오픈 소스 반도체 시뮬레이션 작업공간입니다. 즉시 계산하는 NMOS 계산기부터 실제 로컬 PN 접합·2D MOSFET 해석까지, 소자의 치수·도핑·인가 전압이 전기적 특성에 미치는 영향을 살펴볼 수 있습니다.

## 무엇을 할 수 있나요?

- NMOS 파라미터를 바꾸며 계산된 전류와 I-V 곡선을 즉시 확인합니다.
- 로컬에서 실제 DEVSIM PN·2D MOSFET 템플릿을 실행하고 전위·캐리어·도핑 분포를 살펴봅니다.
- 실험용 CLI 작업 흐름으로 지원되는 SUPREM 공정 결과를 소자 해석에 연결합니다.
- 로컬 결과를 다시 열고 비교·내보내기하거나, 선택형 로컬 MCP로 신뢰하는 AI 클라이언트를 연결합니다.

**[TCAD란 무엇이며, OpenTCAD에서 어떤 시뮬레이션을 할 수 있나요?](docs/ko/simulation-guide.md)** 에서 기본 개념, 지원 실험, 입력과 결과, 모델의 한계를 설명합니다.

## 시작하기

[웹 앱 열기](https://jtech-co.github.io/OpenTCAD/)로 솔버 설치 없이 계산기를 사용하세요. 기본 언어는 영어이며 **한국어**를 선택하면 전환됩니다.

브라우저 앱을 로컬에서 실행하려면 Node.js 22/24와 npm 10 이상을 설치한 뒤 다음 명령을 실행합니다.

```bash
npm ci
npm run dev
```

실제 시뮬레이션에는 별도로 설치한 솔버와 로컬 서비스가 필요합니다.

- [Windows 설치, 작업 기록과 백업](docs/ko/windows-mvp.md)
- [Windows·macOS·Linux 실험실 설치](docs/ko/mvp-laboratory.md)
- [SUPREM·MCP를 포함한 전체 안내](docs/README.ko.md)

## 현재 제공 범위

OpenTCAD은 교육·수치 실험을 위한 Windows 우선 로컬 MVP 후보입니다. GitHub Pages에서는 해석식 계산기와 참조 화면이 동작하며 네이티브 솔버는 실행되지 않습니다. 로컬 해석은 지원되는 고정 템플릿을 사용하며, 즉시 계산이나 범용 공정 편집기가 아닙니다. 다른 운영체제의 제품 자격 검증은 아직 완료되지 않았습니다.

결과는 보정된 제조 공정 승인 자료가 아니며 실제 측정을 대체하지 않습니다. [시뮬레이션 안내](docs/ko/simulation-guide.md)와 [릴리스 범위](docs/ko/product-scope.md)를 확인하세요.

## 라이선스

OpenTCAD 고유 코드와 문서는 [MIT 라이선스](LICENSE)를 사용합니다. 솔버는 별도로 설치하며 각자의 조건을 유지합니다. [라이선스와 고지](docs/ko/licensing.md)를 참고하세요.

Copyright © 2026 JTech-CO.
