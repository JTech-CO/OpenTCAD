# M0 현행 아키텍처 기록

[English](../../en/m0/current-architecture.md) | [M0 상태](README.md)

## M0 시작 시 OpenTCAD 목표 저장소

현재 OpenTCAD은 한·영 React 및 Vite 정적 애플리케이션, 결정론적 참조 미리보기 데이터, 문서, GitHub Pages 배포로 구성됩니다. Backend, database, queue, worker, container runtime adapter, solver source, solver binary, solver image는 없습니다.

정적 애플리케이션은 유용한 제품 셸이지만 시뮬레이션 서비스는 아닙니다. 라이선스와 수치 기준선이 열려 있는 동안 browser-only 경계를 의도적으로 유지합니다.

## 고정된 동작 참조

Commit `13bce4a9daba5796ceee633fb8cd0c870465f766`의 읽기 전용 참조본은 다음과 같은 별도 운영 시스템을 설명합니다.

```text
Browser
  -> React frontend
  -> FastAPI backend
  -> PostgreSQL 및 Redis
  -> worker 및 job 상태
  -> job별 rootless Podman sandbox
       -> SUPREM-IV.GS 공정 이미지
       -> Gmsh remesh 이미지
       -> DEVSIM 소자 이미지
  -> 로그, 구조, curve, artifact
```

이 그림은 외부에서 의미가 있는 구성 요소와 신뢰 경계를 기록합니다. 참조 구현 복사를 허가하지 않습니다.

## 목표 아키텍처 방향

```text
GitHub Pages
  -> 엔진 없는 정적 미리보기 및 문서

Loopback-only local service
  -> 한·영 web UI
  -> API 및 영속 job 상태
  -> runtime-neutral sandbox broker
       -> Docker adapter
       -> Podman adapter
  -> 별도 정책을 적용하는 engine package
       -> process
       -> remesh
       -> device
```

Runtime contract에는 불변 engine identity, 관리형 job storage, 기본 network 차단, read-only root, non-root user, capability 제거, 명시적 CPU·memory·PID·time·output limit, 구조화된 failure semantics가 필요합니다.

## M0에서 기록한 차이

- OpenTCAD local API, worker, job state, runtime adapter, installer가 아직 없습니다.
- 참조본은 가변 base 및 service image tag를 사용합니다.
- 배포 금지 OpenTCAD 관찰 계획은 외부 SUPREM recipe를 고정 base manifest와 Debian snapshot으로 변환하지만 release recipe는 승인되지 않았습니다.
- WSL2 rootless Podman은 1D case 1개에서 선언 profile을 충족했지만 사용 권한이 확인된 OpenTCAD 기준선은 승인되지 않았습니다.
- Docker Desktop과 WSL2 Podman 사전 관찰은 수행했으며 native Linux, Podman Machine, macOS, 전체 장애 동작은 열려 있습니다.
- 솔버 배포와 패치 권리가 승인되지 않았습니다.
- 불변 입력, engine, metric, tolerance를 고정하기 전에는 과학적 결과를 비교할 수 없습니다.

이 차이 때문에 M0는 열린 상태이며 runtime 구현 전에 필요한 증거가 정해집니다.
