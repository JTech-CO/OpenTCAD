# M3 제품 진입 게이트

[English](../en/m3-entry-gates.md)

OpenTCAD에는 로컬 제품 서비스 연결 계층이 구현되어 있지만 제품 활성화는 아직 차단되어 있습니다. 코드 구현 완료는 런타임, 라이선스, 수치 검증, 플랫폼, 실제 전원 차단 증거를 대신하지 않습니다.

## 구현된 제품 경로

- Docker 및 Podman OCI 어댑터는 shell을 사용하지 않는 bounded subprocess transport를 사용합니다.
- 모든 런타임 객체는 정확한 job ID, owner ID, fencing generation을 기록합니다. 어댑터는 작업 전후에 durable authority를 검사하고 mutation 전에 실제 객체 label을 검사하며 객체 생성 직후에도 label을 검사합니다.
- 런타임 권한은 backend, 불변 image identity, 설정된 entrypoint의 정확한 조합으로 부여됩니다. 개별 승인 목록을 임의로 조합하지 않습니다.
- API는 숫자로 된 loopback 주소에만 바인딩하고 peer, Host, Origin, bearer secret, 요청 크기, JSON 형식, 중복 key를 검사합니다.
- 제한된 실행 lane과 별도 control lane을 사용해 solver 실행 중에도 취소를 전달합니다.
- API를 열기 전에 startup recovery를 완료합니다. 실행, 취소, 유지보수, 인증 export 및 import, 예약 backup, 종료는 하나의 lifecycle assembly를 공유합니다.
- Windows Credential Manager, macOS Keychain, Linux Secret Service 어댑터는 API secret과 HMAC key를 애플리케이션 backup 밖에 저장합니다.
- OS 자격 증명 저장소에 두 번째 monotonic restore floor를 보관하고 import 전에 증가시킵니다.

## 구현 파일 지도

| 경로 | 책임 |
|---|---|
| `backend/app/product/gates.py` | 정확한 증거 hash 기반 제품 활성화와 runtime grant |
| `backend/app/runtime/oci_backend.py` | Docker 및 Podman 명령 transport, hardening, image identity, native object fencing |
| `backend/app/service/product_composition.py` | 고정된 M2 composition을 보존하고 일치하는 활성화 token을 요구하는 M3 전용 bridge |
| `backend/app/service/worker.py` | Typed lifecycle queue, 별도 cancellation lane, admission heartbeat, offline import 중재 |
| `backend/app/service/local_api.py` | 인증 loopback HTTP 경계와 strict 요청 codec |
| `backend/app/service/credentials.py` | Windows, macOS, Linux 자격 증명 adapter |
| `backend/app/service/anti_rollback.py` | OS 보호 monotonic restore floor |
| `backend/app/service/scheduler.py` | Restart-safe 예약 backup wake-up loop와 보존되는 failure 상태 |
| `backend/app/service/application.py` | Recovery-first 제품 service assembly와 종료 순서 |
| `tools/qualify-runtime.py` | 승격 권한이 없는 host 관측 도구 |

## 게이트 상태

| 게이트 | 구현 상태 | 자격 또는 승인 상태 |
|---|---|---|
| Docker 및 Podman 어댑터 | 구현 및 fake CLI test 완료 | 차단: 관측한 Windows host에서 Docker daemon 미응답, Podman 미설치 |
| Native fencing | 구현 및 label 변조, stale owner test 완료 | 차단: 실제 Docker 또는 Podman 객체 증거 없음 |
| 로컬 API 및 worker transport | 구현 및 loopback socket test 완료 | 릴리스 검토 대기 |
| Lifecycle 통합 | 구현 및 SQLite assembly test 완료 | 릴리스 검토 대기 |
| OS 자격 증명 및 예약 backup | 3개 OS 어댑터와 scheduler 구현 | 차단: Windows DPAPI test만 있으며 3개 OS native 증거 미완료 |
| 전원 차단 및 비정상 종료 | process hard exit 경계 8곳 통과 | 차단: 실제 abrupt power run은 요구된 100회 중 0회 |
| Windows, macOS, Linux 자격 | CI host contract matrix와 관측 도구 구현 | 차단: 3개 native runtime 행 미승인 |
| Solver release | 실패 폐쇄 게이트 구현 | 차단: 승인된 solver license 기록, 불변 image digest, SBOM, 수치 baseline 없음 |

권위 있는 상태는 [M3 게이트 매니페스트](../../validation/manifests/m3-entry-gates.json)에 있습니다. npm run check:m3가 증거 hash를 검사합니다. productEnabled가 false인 동안 매니페스트는 런타임 권한을 하나도 부여하지 않습니다.

## 검증

    npm run check:m3
    python -m unittest backend.tests.product.test_gates backend.tests.runtime.test_oci_backend backend.tests.service.test_credentials backend.tests.service.test_anti_rollback backend.tests.service.test_worker_scheduler backend.tests.service.test_local_api backend.tests.service.test_application
    python tools/qualify-runtime.py --output validation/evidence/m3/runtime-host-local.json

런타임, 승인 image, 계약 test, native conformance 증거가 모두 준비될 때까지 자격 도구는 blocked 상태와 0이 아닌 종료 코드를 반환합니다. 생성한 파일은 관측 기록이며 승인 기록이 아닙니다.

## 활성화 규칙

8개 게이트 모두 검토된 hash 기반 증거를 가져야 합니다. Docker와 Podman에는 image 및 entrypoint 조합별 grant가 필요하며 전역 승인 정보도 있어야 합니다. 파일 누락, hash 변경, 중복 JSON key, 부분 승인 또는 비활성 제품 표시는 런타임 socket에 접촉하기 전에 token 생성을 차단합니다.

실제 전원 차단 증거는 [외부 전원 차단 검증 절차](../../validation/power-loss/README.ko.md)를 따라야 합니다. Process exit, VM reset, 일반적인 OS 종료는 이 게이트를 충족하지 않습니다.
