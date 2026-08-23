# TCAD Webapp Cross-Platform Porting — Codex Engineering Harness

> **용도:** Codex, Claude Code, 기타 코딩 에이전트가 이 저장소에서 변경을 수행할 때 적용하는 단일 작업 규약  
> **원칙:** 보안·수치 정확성·데이터 보존을 편의보다 우선한다.  
> **적용 범위:** 문서, 프런트엔드, FastAPI, DB, job worker, runtime adapter, Sandbox Broker, Containerfile, SUPREM patches, DEVSIM workflow, CI, packaging

---

## 0. 프로젝트 변수

```yaml
project:
  upstream: https://github.com/ypooh2042/tcad-webapp
  upstream_default_branch: master
  fork: TO_BE_DECIDED
  product_name: TCAD Webapp Cross-Platform Port
  primary_language: ko-KR
  supported_modes: [local, shared, server]
  runtime_backends: [docker, podman]
  baseline_solver_versions:
    suprem_upstream_commit: read-from-SUPREM4GS/upstream/PROVENANCE.md
    devsim: 2.10.1
    gmsh: read-from-image-lock
  baseline_platform: linux/amd64
  release_platforms:
    - windows-11-x64-docker-desktop-wsl2
    - windows-11-x64-podman-machine
    - macos-arm64-docker-desktop
    - macos-arm64-podman-machine
    - macos-x64-docker-desktop
    - linux-x64-rootless-podman
    - linux-x64-docker-engine
```

`TO_BE_DECIDED` 값은 M0에서 확정한다. 에이전트가 임의로 제품명·라이선스·fork 정책을 결정하지 않는다.

---

## 1. Mission

이 하네스의 목적은 다음 네 가지를 동시에 달성하는 것이다.

1. Windows/macOS/Linux에서 동일한 로컬 웹앱 흐름을 제공한다.
2. 사용자의 `.in`이 임의 셸 코드로 동작할 수 있다는 위협 모델을 유지한다.
3. 플랫폼 포팅이 공정 구조·도핑·전극·I–V 결과를 조용히 바꾸지 않게 한다.
4. 변경마다 재현 가능한 테스트·수치 보고·rollback 경로를 남긴다.

작업의 완료 기준은 “코드가 빌드됨”이 아니라 **보안 불변식, 수치 기준선, 상태 전이, 지원 플랫폼 테스트를 통과함**이다.

---

## 2. 절대 불변식

다음 항목을 위반하는 변경은 구현하지 말고 즉시 중단·보고한다.

### 2.1 사용자 입력·실행 경계

- 사용자 입력을 shell command, argv, image name, host path, mount option, environment key, entrypoint에 삽입하지 않는다.
- 사용자 `.in`은 고정 파일명으로만 전달한다.
- `shell=True`, `bash -c <user-data>`, 문자열 command concatenation을 사용하지 않는다.
- 웹/API가 Docker/Podman socket 또는 raw runtime API에 직접 접근하지 않는다.
- 임의 이미지·임의 command·임의 mount를 허용하는 일반 목적 endpoint를 만들지 않는다.

### 2.2 샌드박스

다음 제약을 완화하지 않는다.

- network none
- capabilities drop all
- no-new-privileges
- read-only root filesystem
- fixed non-root UID/GID
- one isolated writable job volume
- CPU/memory/PID/time/output limits
- runtime socket/device/host namespace 미노출
- immutable image digest allowlist

런타임이 필수 옵션을 지원하지 않으면 fallback하지 않고 `RUNTIME_POLICY_UNSUPPORTED`로 실패한다.

### 2.3 상류와 패치

- `SUPREM4GS/upstream/`를 직접 수정하지 않는다.
- SUPREM 코드 수정은 `docker/suprem/patches/`의 순서가 있는 patch로 남긴다.
- patch에는 원인, 재현, 수치 영향, upstream line, regression test를 적는다.
- provenance와 patchset hash를 갱신한다.
- 이미 존재하는 patch의 순서를 바꾸지 않는다. 불가피하면 전체 골든 코퍼스를 재검증한다.

### 2.4 수치 기준선

- 골든 파일·허용오차를 테스트 통과 목적으로 임의 갱신하지 않는다.
- 포팅 PR에서 solver 버전, material model, convergence tolerance를 동시에 바꾸지 않는다.
- floating mismatch를 무조건 tolerance 확대로 숨기지 않는다.
- non-converged/skipped point를 solved로 기록하지 않는다.
- NaN/Inf를 0으로 치환해 계속 진행하지 않는다.

### 2.5 데이터

- migration 전에 backup/restore 경로를 정의한다.
- import는 staging 검증 후 atomic commit한다.
- 기존 프로젝트를 묵시적으로 다시 계산하거나 overwrite하지 않는다.
- local mode 외부 바인딩에서 인증을 생략하지 않는다.

### 2.6 라이선스

- 저장소 전체를 “MIT”라고 단정하지 않는다.
- SUPREM·Gmsh·DEVSIM의 라이선스·NOTICE를 삭제하거나 앱 코드 라이선스로 덮지 않는다.
- 라이선스가 불명확한 바이너리·이미지를 release asset으로 게시하지 않는다.

---

## 3. 작업 시작 전 읽기 순서

모든 에이전트는 작업 범위에 관계없이 다음을 먼저 확인한다.

1. `README.md`
2. `docs/CODEMAPS/README.md`
3. 작업 영역의 코드맵
   - simulator: `docs/CODEMAPS/simulator.md`
   - backend: `docs/CODEMAPS/backend.md`
   - frontend: `docs/CODEMAPS/frontend.md`
4. `backend/app/runner/sandbox.py`
5. `backend/app/runner/runner.py`
6. `backend/app/core/config.py`
7. `docker/*/Containerfile`
8. 관련 테스트와 최근 20개 commit message
9. 이 하네스와 `01_PRODUCT_TECHNICAL_PLAN_KR.md`
10. 해당 milestone의 entry/exit criteria

읽지 않은 파일을 추측으로 수정하지 않는다. 경로나 함수명이 계획 문서와 다르면 실제 코드가 우선이며, 차이를 작업 보고에 기록한다.

---

## 4. 변경 위험 등급

| Level | 범위 | 필수 리뷰·게이트 |
|---|---|---|
| L0 | 문서, typo, 비실행 메타데이터 | 문서 검토 |
| L1 | UI 표시, 비즈니스 로직에 영향 없는 FE | unit + UI/E2E 관련 테스트 |
| L2 | API, DB query, 상태 관리, storage | backend unit/integration + migration/rollback |
| L3 | worker, runtime, broker, sandbox, container lifecycle | security contract + real runtime E2E + fault injection |
| L4 | `.str` parser, remesh, DEVSIM model, SUPREM patch, tolerance | 전체 골든 코퍼스 + 수치 보고 + 2인 승인 |
| L5 | 라이선스·배포 이미지·release signing | maintainer + 법률/배포 승인 |

한 PR이 여러 Level을 포함하면 가장 높은 등급을 적용한다. 가능하면 L3/L4 변경을 UI refactor와 같은 PR에 섞지 않는다.

---

## 5. Issue Intake Contract

작업을 시작하기 전에 이 형식으로 issue 또는 scratch report를 작성한다.

```markdown
## Problem
관찰된 증상과 사용자의 영향. 추측이 아니라 재현 가능한 사실.

## Classification
- Priority: P0/P1/P2/P3
- Risk level: L0–L5
- Domain: frontend/backend/runtime/sandbox/numerical/data/licensing/docs

## Reproducer
최소 입력, 환경, 명령, 기대 결과, 실제 결과.

## Baseline
- commit:
- host/runtime/architecture:
- image digests:
- DB schema:
- solver versions:

## Hypothesis
원인 후보와 반증 방법.

## Invariants at risk
보안·수치·데이터·상태 불변식.

## Planned boundaries
수정할 파일/모듈, 수정하지 않을 범위.

## Tests first
실패해야 하는 characterization/regression test.

## Rollback
변경을 되돌릴 방법과 데이터 영향.
```

재현 없이 대규모 refactor부터 시작하지 않는다. 재현이 불가능하면 관측성을 먼저 추가한다.

---

## 6. 표준 작업 루프

### Step 1 — Baseline 고정

- 현재 commit과 branch를 기록한다.
- 현재 unit/integration/E2E 결과를 기록한다.
- 수치 작업이면 관련 골든 test를 최소 3회 반복한다.
- runtime 작업이면 container/volume 목록과 runtime version을 기록한다.
- 새 실패가 기존 failure인지 구분한다.

### Step 2 — 최소 실패 테스트 작성

- 버그는 수정 전에 실패하는 test 또는 deterministic diagnostic로 재현한다.
- UI 입력 버그는 `fill()`만 사용하지 말고 실제 key sequence와 중간 상태를 테스트한다.
- race는 인위적 delay/abort/controller로 재현한다.
- sandbox는 mock argv snapshot뿐 아니라 실제 runtime에서 정책을 확인한다.
- 수치 결함은 구조/곡선의 핵심 metric을 assertion한다.

### Step 3 — 원인 범위 축소

- 한 번에 하나의 가설만 검증한다.
- 로그를 늘릴 때 secret/source 전체를 출력하지 않는다.
- old C 문제는 sanitizer/debug build와 최소 deck을 사용한다.
- Docker/Podman 차이는 domain logic에서 우회하지 말고 adapter capability에서 분리한다.

### Step 4 — 최소 변경

- public contract를 유지한다.
- 새 abstraction은 실제로 두 backend가 필요할 때 도입한다.
- broad rename/formatting을 기능 변경과 분리한다.
- compatibility shim에는 제거 조건과 milestone을 적는다.

### Step 5 — 다층 검증

- 변경 파일 unit
- 관련 integration
- 전체 backend/frontend suite
- 해당 real runtime E2E
- 수치 골든
- fault injection
- cleanup/orphan 검사
- migration/backup이 관련되면 restore

### Step 6 — 보고

PR 또는 작업 결과에 다음을 포함한다.

```markdown
## Result
무엇이 바뀌었고 사용자에게 어떻게 보이는가.

## Root cause
증상과 원인을 연결한 설명.

## Files changed
책임 경계별 목록.

## Tests
실행한 명령, 통과/실패, skip 이유.

## Numerical delta
비교 대상, metric, before/after, tolerance. 해당 없음이면 이유.

## Security delta
sandbox/runtime/input/data 경계 영향. 해당 없음이면 이유.

## Platform evidence
host/runtime/architecture와 결과.

## Migration and rollback
schema/data/config 영향과 되돌리기.

## Known limitations
남은 위험과 후속 issue.
```

---

## 7. Branch·Commit·PR 규칙

### 7.1 Branch

- `feat/runtime-docker-adapter`
- `fix/devsim-interface-identity`
- `test/numerical-corpus-nmos`
- `docs/windows-install`
- `chore/license-inventory`

한 branch는 하나의 issue 또는 강하게 결합된 work package만 다룬다.

### 7.2 Commit

권장 prefix:

- `feat(runtime): ...`
- `fix(sandbox): ...`
- `fix(devsim): ...`
- `test(numerical): ...`
- `refactor(worker): ...`
- `docs(porting): ...`
- `build(images): ...`
- `chore(license): ...`

commit body에는 재현·원인·왜 이 경계에서 고쳤는지·시험을 적는다. “fix bug”, “support Windows” 같은 모호한 메시지는 금지한다.

### 7.3 PR 크기

- 목표: 400 changed lines 이하, 생성 파일·golden fixture 제외
- L3/L4는 가능한 한 250 logical lines 이하
- 큰 migration은 schema, data backfill, UI 전환을 단계별 PR로 나눈다.

---

## 8. Runtime Adapter 작업 규약

### 8.1 계약 우선

새 backend를 만들기 전에 공통 contract test를 만든다.

필수 capability:

- runtime health/version/architecture
- image inspect/pull/build/digest
- managed volume create/remove
- validated input transfer
- container create/start/wait/kill/remove
- stdout/stderr streaming 또는 bounded capture
- CPU/memory/PID/timeout
- network none, cap drop, read-only, no-new-privileges, non-root
- labels와 orphan query/cleanup
- artifact transfer

### 8.2 금지 패턴

- `if windows: ...`를 domain worker 곳곳에 추가
- Docker와 Podman argv를 같은 함수에서 문자열 분기
- capability가 없을 때 option을 빼고 실행
- host workdir를 Desktop VM에 그대로 넘기고 우연히 작동하기를 기대
- runtime CLI의 locale-dependent error string만으로 상태 판정

### 8.3 Adapter Definition of Done

- mock contract test 통과
- Docker real runtime test 통과
- Podman real runtime test 통과
- 동일 fake solver workload의 artifact/hash/status 일치
- kill/timeout/OOM/output-limit 분류 일치
- 정책 inspect test 통과
- orphan cleanup test 통과
- runtime이 꺼진 상태와 stale state를 stable code로 분류

---

## 9. Sandbox Broker 작업 규약

- Broker 입력은 typed `SandboxSpec`만 허용한다.
- image는 config allowlist + digest로 확인한다.
- entrypoint는 image metadata와 서버 registry에서 고정한다.
- env는 profile ID로만 선택하고 raw map을 받지 않는다.
- job volume 이름은 server UUID에서 생성한다.
- 모든 runtime object에 label을 붙인다.
- broker는 앱 DB 데이터를 직접 해석하지 않는다.
- worker는 broker의 stable error와 artifact manifest만 소비한다.
- broker API는 외부 웹에 노출하지 않는다.
- raw runtime error는 내부 로그에 남기되 사용자 메시지는 redacted한다.

Fault injection cases:

1. runtime process/VM stopped
2. image missing or corrupted
3. container creation returns permission error
4. solver hangs
5. solver writes beyond output limit
6. solver creates symlink/device node
7. worker dies after container start
8. broker dies before cleanup
9. host restarts with RUNNING job
10. kill arrives during remesh→DEVSIM transition

모든 case에서 DB 상태, container/volume cleanup, 사용자 error code가 예상대로여야 한다.

---

## 10. 플랫폼별 작업 체크리스트

### 10.1 Windows 11 / WSL2

- PowerShell path quoting과 UTF-16/UTF-8 경계 확인
- CRLF source normalization
- project data는 engine-managed volume을 기본으로 함
- 개발 bind mount는 WSL Linux filesystem을 우선 안내
- drive letter/UNC/reserved name/long path test
- Docker Desktop VM memory/disk 부족 진단
- WSL/Docker restart 후 compose·job recovery
- Windows firewall 경고 없이 loopback 접근
- browser open과 port collision 처리

### 10.2 macOS Intel

- Docker Desktop와 Podman Machine 모두 확인
- file sharing permission과 volume export
- case-insensitive filesystem collision test
- sleep/wake 후 runtime health와 stale connection
- Gatekeeper/launcher 실행 안내

### 10.3 macOS Apple Silicon

- 각 image의 실제 platform 확인
- amd64 emulation 사용 시 UI/provenance에 표시
- SUPREM native arm64 build는 별도 branch/PR
- native vs emulated 골든 비교
- QEMU/Rosetta 사용 시 timeout·성능 기준 별도
- mixed-platform Compose pull/build 확인

### 10.4 Linux

- rootless Podman 회귀 유지
- Docker Engine backend 병행
- SELinux host에서는 volume label 정책 확인
- systemd/Quadlet 서버 프로필 회귀
- user namespace/pause 복구는 Podman adapter 내부에 제한

---

## 11. 수치·과학 변경 프로토콜

### 11.1 변경 전

- 관련 골든 case와 metric을 선언한다.
- 동일 환경에서 5회 반복해 자연 분산을 측정한다.
- baseline image digest와 solver version을 기록한다.
- 결과 차이가 발생할 수 있는 수학적 이유를 적는다.

### 11.2 변경 중

- solver code, mesh policy, parser, unit conversion, convergence policy를 한 PR에 둘 이상 바꾸지 않는다.
- remesh 전후 topology/contact preservation을 검사한다.
- 계산 실패 시 last-known-good rollback을 보장한다.
- fallback을 사용하면 result manifest에 기록한다.

### 11.3 변경 후 보고서

```markdown
# Numerical Validation Report
- Change:
- Baseline commit/image/platform:
- Candidate commit/image/platform:
- Corpus cases:
- Topology comparison:
- Geometry metrics:
- Field metrics:
- I–V metrics:
- Repeated-run variance:
- Tolerance used and rationale:
- Warnings/skipped points:
- Conclusion: PASS / FAIL / NEEDS REVIEW
```

### 11.4 Baseline 갱신 조건

다음 모두를 만족해야 한다.

- 의도된 물리/수치 변경 RFC 존재
- 기존 결과가 왜 잘못되었는지 재현
- 새 결과를 independent invariant 또는 외부 reference로 검증
- 전체 corpus 영향 분석
- maintainer 2인 또는 maintainer + domain reviewer 승인
- release notes와 project provenance schema 갱신

포팅·리팩터링만을 이유로 baseline을 갱신하지 않는다.

---

## 12. Security 작업 프로토콜

### 12.1 Threat model 검토 대상

- malicious `.in` shell execution
- command/argument injection
- path traversal, symlink/hardlink escape
- zip/tar bomb
- container escape
- runtime socket privilege escalation
- host bind mount overwrite
- cross-job/cross-user artifact access
- output/log/database exhaustion
- stale container/volume takeover
- local auth bypass with external bind

### 12.2 보안 변경 보고

- 공격자가 제어하는 데이터
- 신뢰 경계
- 변경 전/후 권한
- 실패 시 최대 영향
- 정책을 검사하는 automated test
- Desktop VM과 Linux host 차이
- residual risk

### 12.3 보안 중단 조건

다음이 필요해 보이면 코드를 쓰지 말고 설계를 재검토한다.

- `--privileged`
- host root 경로 mount
- runtime socket을 solver/worker/web에 전달
- network를 solver에 열기
- seccomp/capability/no-new-privileges 제거
- 사용자 지정 image/command 허용
- local no-auth를 `0.0.0.0`에 노출

---

## 13. Frontend·상태 관리 규약

- 사용자가 타이핑 중인 문자열과 validated numeric value를 분리한다.
- stable identity로 사용자 편집 label을 사용하지 않는다.
- 요청은 job_id/step_id/revision과 묶고 stale response를 버린다.
- query polling payload에 전체 log를 싣지 않는다.
- 화면 전환이 서버 job을 중단하지 않는다면 불필요한 confirmation을 띄우지 않는다.
- partial/non-converged 결과를 성공 곡선처럼 그리지 않는다.
- 같은 정보의 이름·단위·color semantics를 공정/소자/비교 화면에서 통일한다.
- canvas 최적화는 구조 layer와 interaction overlay를 분리한다.

UI bug test는 가능한 한 실제 키 입력, focus/blur, rapid navigation, slow response, abort를 포함한다.

---

## 14. DB·Migration·Project Import 규약

- migration은 additive → backfill → switch-read → remove-old의 순서로 분리한다.
- destructive migration 전에 backup fixture와 restore test를 만든다.
- DB schema version과 `.tcadproj` schema version을 혼동하지 않는다.
- import archive는 임시 디렉터리/volume에서 검증한다.
- duplicate project/file/interface IDs를 명시적으로 처리한다.
- import 실패 시 기존 DB와 storage에 변화가 없어야 한다.
- migration 중 worker를 정지하거나 compatible state를 정의한다.

---

## 15. 테스트 명령과 게이트

실제 명령은 저장소 변경에 따라 README와 package metadata를 기준으로 갱신한다.

### Backend

```bash
cd backend
.venv/bin/python -m pytest
.venv/bin/python -m pytest -m "not integration"
```

### Frontend

```bash
cd frontend
npm run lint
npm run test
npm run coverage
npm run e2e
```

### Container/runtime

- Docker adapter contract
- Podman adapter contract
- image build for target platform
- policy inspection
- real solver smoke
- orphan cleanup

### PR gate by level

| Level | 최소 게이트 |
|---|---|
| L0 | link/spell/markdown validation |
| L1 | frontend lint + relevant unit + E2E slice |
| L2 | backend full + integration + FE affected tests |
| L3 | L2 + Docker/Podman contract + real runtime + fault injection |
| L4 | L3 + complete numerical corpus + validation report |
| L5 | L4 + license inventory + release dry-run + approval |

테스트 skip은 “환경이 없음”만으로 허용하지 않는다. 지원 플랫폼 gate라면 self-hosted/manual evidence를 연결한다.

---

## 16. Definition of Done

### 기능

- acceptance scenario가 자동화 또는 명시적 qualification로 통과
- error/empty/loading/cancel/retry 상태 구현
- backward compatibility 또는 migration 제공

### 버그

- 실패 test가 수정 전 실패하고 수정 후 통과
- 같은 root cause의 인접 경로를 점검
- silent correctness라면 invariant 추가

### Runtime/Sandbox

- 공통 policy와 backend-specific mapping 분리
- Docker/Podman real evidence
- orphan 0
- fault injection
- 보안 delta 문서

### 수치

- 전체 관련 corpus 통과
- metric delta 보고
- topology·unit·convergence warning 확인
- baseline 무단 변경 없음

### 데이터

- migration, backup, restore, rollback
- import atomicity
- version/provenance 기록

### 문서/릴리스

- 플랫폼별 install/update/uninstall
- release notes
- license/NOTICE/SBOM
- known limitation

---

## 17. Stop / Escalation Conditions

에이전트는 다음 상황에서 더 진행하지 않고 `BLOCKED` 보고를 남긴다.

1. 배포할 구성의 라이선스 권한이 불명확함
2. 수치 차이가 허용오차를 넘지만 원인이 분리되지 않음
3. 필수 sandbox 정책을 특정 runtime이 구현하지 못함
4. 해결을 위해 사용자 입력을 command/path/env에 넣어야 함
5. migration이 데이터 손실 없이 rollback되지 않음
6. native arm64 빌드가 기존 포인터·메모리 가정을 깨고 결과를 바꿈
7. upstream 최신 변경과 작업 branch가 같은 영역에서 충돌하며 의도를 알 수 없음
8. 테스트가 비결정적이고 수정 효과를 판정할 수 없음
9. secret, invite code, personal source가 commit에 포함될 위험
10. release artifact에 출처를 설명할 수 없는 바이너리가 포함됨

보고 형식:

```markdown
STATUS: BLOCKED
Decision needed:
Evidence:
Options:
Risk of each option:
Recommended next action:
Files left unchanged:
```

---

## 18. Codex 시작 프롬프트

아래 블록을 milestone/issue별 작업 시작에 붙여 사용할 수 있다.

```markdown
# Role
당신은 TCAD Webapp Cross-Platform Port의 구현 에이전트다. 구현보다 보안·수치 재현성·데이터 보존을 우선한다.

# Required reading
README.md, docs/CODEMAPS/*, backend/app/runner/sandbox.py,
backend/app/runner/runner.py, 관련 Containerfile, 관련 테스트,
02_CODEX_HARNESS_KR.md, 현재 milestone 문서를 먼저 읽는다.

# Non-negotiables
- 사용자 입력을 command/argv/image/host path/env/entrypoint에 넣지 않는다.
- sandbox 정책을 완화하지 않는다.
- SUPREM4GS/upstream을 직접 수정하지 않는다.
- 포팅과 solver 버전/물리 모델 변경을 섞지 않는다.
- 골든 baseline을 테스트 통과 목적으로 갱신하지 않는다.
- 데이터 migration에는 backup/restore/rollback을 포함한다.

# Task
<ISSUE 내용을 여기에 삽입>

# Before editing
1. 현재 구조와 관련 test를 요약한다.
2. 최소 재현과 실패 test 계획을 제시한다.
3. 변경 파일 경계와 위험 등급을 제시한다.
4. 불명확한 라이선스·수치·보안 결정이 있으면 BLOCKED로 멈춘다.

# Required output
- Root cause
- Files changed
- Tests run and results
- Numerical delta
- Security delta
- Platform evidence
- Migration/rollback
- Remaining risks
```

---

## 19. Milestone별 에이전트 권한

| Milestone | 허용 중심 | 금지 중심 |
|---|---|---|
| M0 | 문서·inventory·baseline script·tests | runtime behavior/solver 변경 |
| M1 | corpus·comparator·CI foundation | baseline 수치 갱신 없이 solver 수정 |
| M2 | runtime contract, adapters, broker | UI 대규모 재설계, model upgrade |
| M3 | Compose, launcher, local mode | public exposure default |
| M4 | Windows fixes, docs, qualification | Windows native SUPREM port |
| M5 | macOS/arm64 build and qualification | tolerance 임의 확대 |
| M6 | P0/P1 correctness/data/UX fixes | 새로운 큰 기능 |
| M7 | export/import, provenance, engine registry | arbitrary plugin/user Python |
| M8 | release hardening, notices, installer | late architecture rewrite |

---

## 20. Harness 유지 규칙

- 실제 코드와 불일치하는 명령·경로를 발견하면 같은 PR에서 하네스를 갱신한다.
- 새로운 silent correctness 결함이 발견되면 관련 불변식을 이 문서에 추가한다.
- 새로운 runtime/platform을 지원할 때 capability·qualification checklist를 추가한다.
- 하네스 완화는 security/numerical reviewer 승인이 필요하다.
- 문서가 길어져도 핵심 불변식과 stop condition을 요약본에서 제거하지 않는다.
