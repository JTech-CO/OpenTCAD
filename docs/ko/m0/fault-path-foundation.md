# M0 장애 경로 계약 기반

[English](../../en/m0/fault-path-foundation.md) | [M0 상태](README.md)

이 기반은 솔버나 컨테이너 런타임 없이 프로세스 감독 동작을 검사합니다. Docker, Podman, SUPREM-IV.GS, Gmsh, DEVSIM 또는 제품 worker를 검증하지 않습니다.

## 구현된 통제

[`FaultPathSupervisor`](../../../validation/faults/supervisor.mjs)는 영속 command worker 하나를 관리하고 한 번에 활성 작업 하나만 받습니다. Command는 `shell: false`와 인자 배열을 사용하고 allowlist 환경만 상속하며 timeout과 stdout/stderr 합산 출력 제한을 명시적으로 적용합니다.

| 발생 조건 | 안정 분류 | 격리 동작 | 복구 검증 |
|---|---|---|---|
| 기한 만료 | `timed-out` | 활성 프로세스를 종료하고 제한된 유예 시간 뒤 강제 종료한 후 worker 초기화 | 다음 작업이 새 세대에서 실행되고 성공 |
| `AbortSignal` 발생 | `cancelled` | 활성 프로세스를 종료하고 worker 초기화 | 다음 작업이 다른 worker PID로 실행 |
| 합산 출력이 byte 상한 초과 | `output-limit-exceeded` | 선언된 상한까지만 보관하고 프로세스 종료 후 worker 초기화 | 보관 byte가 상한과 같고 다음 작업 성공 |
| Worker가 결과 없이 종료 | `worker-crashed` | 작업을 실패 처리하고 worker 폐기 | 이후 작업은 새 세대에서 시작해야 함 |

정상 작업은 같은 worker 세대를 재사용합니다. `nonzero-exit`는 실패 작업 분류로 유지하지만 종료가 완료된 자식 프로세스 때문에 supervisor를 초기화하지는 않습니다. Spawn 오류와 protocol 오류는 worker를 초기화합니다.

POSIX host에서는 command를 별도 process group에서 실행하므로 해당 group을 종료 대상으로 삼습니다. 이 기반에서 Windows는 직접 자식 프로세스 signal 경로를 사용합니다. 지원을 주장하려면 runtime adapter에서 container identity, kill, remove, orphan query를 추가로 검증해야 합니다.

## 장애 주입 증거

[`supervisor.test.mjs`](../../../validation/faults/supervisor.test.mjs)는 프로세스 경계를 mock 처리하지 않고 실제 Node 자식 프로세스를 실행합니다. 다음을 검증합니다.

1. 정상 worker 재사용
2. Timeout 분류 후 새 worker에서 다음 작업 성공
3. 취소 분류 후 새 worker에서 다음 작업 성공
4. 합산 출력을 정확한 상한에서 절단한 뒤 복구
5. 잘못된 제한값과 동시 작업 거부

전체 엔진 독립 test suite는 다음과 같이 실행합니다.

```sh
npm run test:validation
```

기계 판독 상태는 [`m0-fault-path-foundation.json`](../../../validation/manifests/m0-fault-path-foundation.json)에 있습니다. `baselinePromotionAllowed`, solver evidence, container runtime evidence는 계속 `false`입니다.

## 남은 런타임 증거

- Docker 및 Podman adapter 계약이 생기면 같은 장애 행렬을 각 adapter에서 반복합니다.
- 불변 job identity로 container cleanup을 검증하고 혼합 반복 후 orphan 수가 0임을 입증합니다.
- 사용 권한이 확인된 input과 image로 실제 SUPREM, remesh, DEVSIM 실행 중 취소를 시험합니다.
- Worker, broker, runtime, host crash를 주입하고 영속 job state 복구를 확인합니다.
- 같은 동작을 native Windows, macOS, Linux에서 검증합니다.

이 계약은 엔진 독립 구현 범위만 완료합니다. BASE-001이나 M0 종료 게이트를 닫지 않습니다.
