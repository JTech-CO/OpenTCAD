# OpenTCAD 문서

[English](README.md) · [OpenTCAD](../README.ko.md)

## 처음 시작하기

- [TCAD와 지원 시뮬레이션](ko/simulation-guide.md): 개념, 입력, 결과, 실험 예시와 한계
- [Windows 로컬 설치](ko/windows-mvp.md): 작업 기록, 취소·복구와 오프라인 백업
- [실험실 설치](ko/mvp-laboratory.md): 계산기와 Windows·macOS·Linux 실험용 솔버 설치

## 기능 사용하기

- [2D MOSFET·SUPREM 연계](ko/mos-process.md): 물리 모델, 수치 범위와 공정 CLI
- [원본 공정 메시](ko/process-mesh.md): 지원 구조 파일과 명시적 전극 지정
- [참조 작업공간](ko/m4-workspace.md): 실제 해석과 별개인 프로젝트 파일, 외부 데이터와 설명용 화면
- [로컬 MCP](ko/mcp.md): 신뢰하는 AI 클라이언트 연결과 명시적 실행 권한

## 제공 범위와 기여

- [제품 및 릴리스 범위](ko/product-scope.md)
- [라이선스](ko/licensing.md)
- [아키텍처](ko/architecture.md)
- [개발](ko/development.md)
- [검증](../validation/README.ko.md)과 [PN 반복 재현성 조사](ko/pn-repeatability.md)

## 유지보수용 참조 자료

M0~M2 문서와 [코드맵](CODEMAPS/README.md)은 계약 검사가 참조하고 M2의 경우 기록된 내용 해시도 검증하므로 기존 경로에 보존합니다. 과거 엔지니어링 증거이며 현재 기능 목록이나 실험실 사용의 선행 조건이 아닙니다.

M3의 [로컬 서비스](ko/m3-local-service.md), [진입 게이트](ko/m3-entry-gates.md), [런타임 검증](ko/m3-native-adapter-conformance.md), [자격 증명](ko/m3-native-credentials.md), [승격](ko/m3-promotion-readiness.md), [솔버 릴리스](ko/m3-solver-release-qualification.md) 문서는 별도로 비활성화된 OCI 제품 트랙의 자료입니다. 일반 Windows MVP 범위의 출시를 차단하거나 해당 기능을 활성화하지 않습니다.

수치 동작·보안·복구를 검사하는 하네스는 유지합니다. 더 이상 현재 상태를 설명하지 않는 구현 범위·원본 사이트 비교 보고서는 삭제했으며 Git 이력에서 확인할 수 있습니다.
