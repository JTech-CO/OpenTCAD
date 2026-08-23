# 기반 작업 보고서

[English](../en/project-foundation.md)

## 문제

대상 저장소에는 67바이트 초기 README만 있었고 작업공간에는 교차 플랫폼 기획서, 엔지니어링 하네스, 로드맵, 백로그, UI 참고 이미지 2개만 있었습니다. 빌드 가능한 애플리케이션, 한·영 제품 문서, GitHub가 인식하는 루트 라이선스, CI, GitHub Pages 산출물이 없었습니다.

## 분류

- 우선순위: P0 기반
- 위험 등급: 라이선스·배포 경계 L5, 정적 UI L1
- 영역: licensing, documentation, frontend, CI
- 업스트림 동작 참고: `ypooh2042/tcad-webapp@13bce4a`
- 대상 기준선: `JTech-CO/OpenTCAD@9325b01`

## 재현

1. 대상 기준선 `9325b01`을 checkout합니다.
2. 짧은 README만 있는 것을 확인합니다.
3. `npm run build`를 실행하면 애플리케이션과 패키지 메타데이터가 없습니다.
4. 저장소 라이선스 메타데이터를 확인하면 인식되는 라이선스가 없습니다.

기대 결과는 정적으로 빌드되는 MIT 고유 한·영 프로젝트 기반과 분리된 제3자 솔버 라이선스 조건입니다.

## 위험 불변식

- 정적 호스트는 제출된 입력을 절대 실행하지 않습니다.
- 브라우저/API 구성요소에는 런타임 소켓을 전달하지 않습니다.
- 참조 미리보기 곡선을 솔버 출력이나 수치 기준선으로 표현하지 않습니다.
- 루트 MIT 라이선스가 SUPREM-IV.GS, Gmsh, DEVSIM에 적용된다고 표현하지 않습니다.
- 기존 기획 문서와 제공된 UI 참고 이미지를 보존합니다.

## 변경 경계

변경: 루트 프로젝트 메타데이터, 영어·한국어 쌍의 제품 문서, 프런트엔드 전용 참조 경험, CI와 Pages workflow.

변경하지 않음: 업스트림 애플리케이션 소스, SUPREM 소스·patch, 솔버 버전, 이미지, 런타임 동작, 데이터베이스, migration, 수치 tolerance, golden result.

## Tests first

기반 작업에는 다음 테스트를 추가합니다.

- 명시적인 정적 모드 실행 경계
- 영어/한국어 전환
- 결정론적 참조 워크플로 상태 전이
- 한·영 번역 key 동등성
- 상대 자산 경로를 사용하는 배포용 정적 compile

## 검증

2026-08-23에 Node.js 24로 다음을 검증했습니다.

- `npm run lint`: 경고 없이 통과
- `npm run test`: 2개 파일, 8개 테스트 통과
- `npm run coverage`: 보고서 생성(전체 28.24%, jsdom에서는 canvas 그리기 경로를 실행하지 않음)
- `npm run build`: TypeScript 및 Vite 배포 빌드 통과, 상대 자산 경로 확인
- `npm audit --audit-level=high`: 취약점 0건
- 로컬 정적 미리보기: `/`와 `/og.png` 모두 HTTP 200
- 제공된 기획 묶음: 기록된 SHA-256 해시 8개 모두 일치

## Rollback

작업은 `feat/project-foundation` 브랜치에 격리합니다. 커밋을 되돌리면 저장소가 초기 README 상태로 돌아가며 데이터베이스, 런타임 객체, 솔버 산출물 또는 사용자 프로젝트에는 영향을 주지 않습니다.

## 알려진 제한

현재 앱은 참조 UI이며 솔버 연결 릴리스가 아닙니다. Docker/Podman adapter, sandbox broker, FastAPI, 영속성, 수치 corpus, launcher, backup, project import/export, 교차 플랫폼 자격 검증은 이후 로드맵 작업입니다.
