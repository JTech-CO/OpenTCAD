# OpenTCAD 마일스톤 로드맵

[English](../en/roadmap.md)

상세 기획 원문은 `03_MILESTONE_ROADMAP_KR.md`입니다. 이 한·영 요약은 공개 제품 순서를 설명하며 마일스톤의 진입·종료 게이트를 대체하지 않습니다.

| 마일스톤 | 결과 | 필수 게이트 |
|---|---|---|
| 기반 | MIT 고유 한·영 정적 앱, Pages, CI, 아키텍처·라이선스 경계 | 정적 모드에서 입력 실행 불가 |
| M0 | 업스트림·의존성 목록, 배포 결정, Linux 기준선, 플랫폼 spike | 라이선스와 기준선 Go/No-Go |
| M1 | 공정·소자 골든 코퍼스, 수치 comparator, 재현 이미지 lock, CI 기반 | 반복 가능한 topology와 metric 증거 |
| M2 | 런타임 계약, Docker/Podman adapter, sandbox broker, 관리 잡 볼륨 | 두 런타임에서 정책 fail-closed |
| M3 | 이식 가능한 로컬 stack, loopback 전용 모드, launcher, doctor, backup 골격 | 단일 명령 local alpha |
| M4 | Windows 11 자격 검증 | Docker Desktop WSL2 E2E와 수치 증거 |
| M5 | macOS 및 multi-architecture 자격 검증 | Apple Silicon native 또는 명시적 amd64 emulation 정책 |
| M6 | correctness, 수치 안정성, 데이터 안전, UX 결함 해소 | 열린 P0/P1과 알려진 silent correctness 결함 0 |
| M7 | 이식 가능한 `.tcadproj`, provenance, 진단, engine registry | OS 간 replay와 안전한 import |
| M8 | 보안, 라이선스, 릴리스 운영, 문서, 전체 자격 검증 | 1.0 GA 게이트와 rollback 증거 |

## 현재 상태

프로젝트 기반 마일스톤은 완료되어 GitHub Pages에 배포되었습니다. SUPREM 고지가 MIT가 아니므로 M0의 솔버 배포 결정은 아직 게이트 상태입니다. 업스트림 애플리케이션은 동작·아키텍처의 읽기 전용 증거로만 사용하며 이 MIT 저장소에 복사하지 않습니다.

## 정적 배포와 로컬 배포

GitHub Pages는 로드맵 전체에서 안전한 제품 미리보기와 문서 표면으로 유지합니다. Pages를 샌드박스 우회 수단으로 사용하지 않습니다. 솔버 실행은 loopback 전용 로컬 stack 또는 인증된 관리 서버에서만 가능합니다.

프로세스 종료만으로 결과를 “성공” 처리하지 않습니다. topology 불변식, 공정 metric, I–V metric, 수렴 의미, provenance, 플랫폼 간 허용오차를 별도 release gate로 유지합니다.
