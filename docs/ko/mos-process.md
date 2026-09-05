# 2D MOSFET 및 SUPREM 연계

[English](../en/mos-process.md) · [실험실 설치](mvp-laboratory.md)

## 실제 실행 기능

선택형 로컬 실험실에서 **실제 2D NMOS**를 해석합니다. 1D 결과를 2D처럼 그리는
기능이 아닙니다. 고정된 DEVSIM 의존성을 설치하고 빌드한 뒤 `npm run local:lab`을
실행합니다. **2D MOSFET 해석**에서 입력을 바꾸고 **2D MOSFET 실행**을 누르세요.
드레인 전압 스윕, 실리콘·산화막 삼각형 메시, 전위, 전자·정공 농도와 순 도핑을
계산합니다. 표시 물리량과 메시 표시를 선택할 수 있으며 입력을 변경하면 이전
결과는 지워집니다. GitHub Pages 정적 빌드는 네이티브 솔버를 실행하지 않습니다.

즉시 계산기, 1D PN 솔버, 2D 솔버는 서로 다른 모델입니다. 두 솔버 화면을 합쳐
동시에 하나의 네이티브 작업만 실행합니다. 취소는 자식 프로세스를 종료하고
회수합니다. 통신 실패만으로 취소가 완료되지는 않습니다. 기록은 세션 내 최대
32건이며 새로고침 전에 결과를 저장해야 합니다.

## 물리 모델과 수치 범위

`devsim-mos-2d-300K-v1`은 DEVSIM `simple_physics`의 Poisson, 전자·정공
드리프트-확산, SRH 재결합을 사용합니다. Boltzmann 통계, 300 K, 진성 농도
1e10 cm^-3, 이동도 400/200 cm²/Vs, 수명 1 μs, 실리콘 유전율 11.7 epsilon0,
산화막 3.9 epsilon0를 고정합니다. 금속 게이트 전위는 진성 실리콘 기준
VG + 0.45 V입니다. 소스·기판 인가 전압은 0 V이며 소스·드레인·기판은 이상적인
옴 접촉입니다. 계면의 전위·전기 변위는 연속이고 산화막은 캐리어를 운반하지
않습니다. 접촉이 없는 외곽은 절연 경계입니다.

게이트 길이 0.5~2 μm, 양쪽 소스·드레인 연장 길이 각각 0.5 μm, 실리콘 깊이
0.5 μm, 폭 1~100 μm, 산화막 5~30 nm, VG 0~1.5 V, VD 0~0.5 V를 지원합니다.
기본 도핑은 p형 기판과 가우시안 도너 꼬리이며 가로 50 nm, 세로 70 nm 척도를
사용합니다. 2배 세분화는 실리콘 메시 간격을 절반으로 줄입니다. 접촉은 게이트
끝에서 0.1 μm 떨어집니다. 2D 단자 전류 A/cm에 소자 폭 cm를 곱해 A로 표시합니다.
지도는 세로축을 확대하고 정점 값 평균으로 셀 색을 표시하므로 실제 종횡비의
제조 도면은 아닙니다.

고전계 이동도, 양자 보정, Fermi-Dirac 축퇴, 충돌 이온화, 터널링, 공정 보정
모델은 없습니다. 허용 범위의 일부 조합도 수렴에 실패할 수 있으며, 실패할 때
해석식이나 참조 결과로 대체하지 않습니다. 특히 고농도 파일은 물리 모델 검토가
필요합니다.

`npm run test:mvp:solver`는 실제 솔버를 실행합니다. 기본 Windows 사례
(L=1 μm, W=10 μm, tox=10 nm, VG=1 V, VD=0.1 V)는 약 105.174 μA였으며,
메시 세분화 전후 전류 차이는 1.0123%였습니다. 이 교육용 사례의 테스트 허용
상한은 10%이며 일반적인 오차 보장은 아닙니다. 게이트 응답, 폭 비례성,
평형 전류, 단조 드레인 전류, 양의 캐리어 농도, 전류 보존, 취소와 재실행도
검사합니다. 각 단계에서 |IS+ID+IB| <= 1e-13 A + 1e-5 max(|단자 전류|)가
필요합니다. Windows·macOS·Linux CI 실행은 M3 제품 승인을 의미하지 않습니다.

## SUPREM 공정 경로

고정 덱 공정 CLI와 기존 SUPREM-IV.GS B.9305 2D `.str` 파일의 엄격한 가져오기를
제공합니다. 솔버 자체는 배포하지 않습니다. Docker에는 연결되지 않았지만
Debian WSL의 Podman에 기존 SUPREM 참조 이미지가 있어 **생성한 공정 덱과 실제
소자 연계를 실행했습니다.** 반복 공정의 STR 바이트가 일치했고, 주입량을
1e14에서 2e14 cm^-2로 변경하면 최종 2D 드레인 전류가 약 115.549에서
119.221 μA로 바뀌었습니다. 반복 STR로 원래 소자 해석을 재실행해 결과도
재현했습니다. 로컬 비기준 관측이며 공정 정확도 보정이나 M3 승인은 아닙니다.
별도의 합성 STR 테스트를 실제 공정 증거로 간주하지 않습니다.

실제 공정 프로파일로 인증된 loopback HTTP 작업 경로도 확인했습니다.
[관측 기록](../../validation/experimental/mos-process-observation.json)에 솔버를
배포하지 않고 이미지·입력 해시와 수치 결과를 남겼습니다.

`/opt/suprem4gs` 구성의 이미지가 이미 설치되어 있다면 Python 표준 라이브러리만
사용하는 컨테이너 CLI를 실행할 수 있습니다. 이미지를 내려받거나 배포하지 않습니다.

```bash
python -m backend.app.experimental.suprem_container --enable-experimental-suprem --runtime podman --image sha256:YOUR_LOCAL_IMAGE_ID --output /absolute/path/new-process-run
```

변경 가능한 태그 대신 전체 64자리 로컬 이미지 ID를 지정합니다. `docker`도
어댑터 옵션이지만 이번 관측에서는 실행하지 않았습니다. 네트워크·호스트 마운트
없이 읽기 전용 루트, 비특권 UID, capability 제거, CPU·메모리·프로세스 수·tmpfs
제한을 적용합니다. 실행별 임시 컨테이너를 제거하고 잔존 여부를 확인합니다.
M3 제품 어댑터나 승인 조건은 사용하지 않습니다. 이 Windows 호스트에서는
프로젝트 디렉토리에서 `wsl.exe -d Debian -- python3 ...`로 실행한 후 생성된
STR을 Windows DEVSIM 실험실에서 읽을 수 있습니다. 캐시 이미지 자체의 M3
재배포 승인은 여전히 미해결 상태입니다.

신뢰하고 사용 권한을 확보한 네이티브 SUPREM 설치가 있다면, 해당 바이너리가
실행되는 OS에서 실험실과 같은 Python 환경으로 실행합니다.

```bash
python -m backend.app.experimental.suprem_process --enable-experimental-suprem --executable /absolute/path/suprem --data-directory /absolute/path/data --output /absolute/path/new-process-run --gate-length 1 --dose 1e14 --energy 30 --minutes 10 --temperature 950
```

붕소 도핑 직사각형 기판에 주입 마스크를 증착·제거하고 인을 주입한 뒤 열처리합니다.
단위는 dose cm^-2, energy keV, minutes 분, temperature 섭씨입니다. 전체 제조
순서나 게이트 산화막 성장은 모델링하지 않습니다. 산화막은 DEVSIM 템플릿에서
추가합니다. CLI는 고정 명령과 제한된 숫자만 전달하며 업로드한 덱은 실행하지
않습니다. 종료 상태와 구조 파일을 확인한 뒤 **새 디렉토리**에 `process.str`,
`process.in`, 출처 JSON을 저장합니다. 실행 파일·물성 데이터·덱 해시를 기록하고
120초 제한 및 진단 출력 크기 제한을 적용합니다. 실패하면 빈 출력 디렉토리가
남을 수 있습니다. 이 명시적 CLI는 **OS 샌드박스가 아니며** 원격에 노출하면
안 됩니다. ELF 바이너리의 네이티브 Windows 실행을 의미하지 않습니다.
필요하면 호환되는 Linux/WSL 환경에서 공정 CLI를 실행하세요.

구조 파일은 서버 시작 시 스냅샷으로 읽습니다.

```bash
python -m backend.app.experimental.suprem /absolute/path/process.str
npm run local:lab -- --suprem-structure /absolute/path/process.str
```

2D 화면에서 **SUPREM 활성 도핑 가져오기**를 선택합니다. 공정 덱과 게이트 길이를
맞춰야 하며 파일이 템플릿의 모든 실리콘 노드를 포함해야 합니다. 가져온 도핑이
기판·도너 입력을 대체하고 해당 입력칸은 비활성화됩니다. 서버는 재시작까지
메모리에 고정 스냅샷을 유지합니다. HTTP로 경로를 받거나 브라우저 덱을 실행하지
않습니다. `processSimulated: false`는 가져오는 서비스가 SUPREM 공정을 직접
실행하거나 보증하지 않았다는 뜻입니다. 파일 해시는 바이트 확인 수단이지
작성자나 정확성 증명은 아닙니다.

전달 범위는 활성 도핑이며 **전체 공정 형상·접촉 가져오기는 아닙니다**.

- STR 좌표는 μm, `c` ID는 1부터, `n` 점 ID는 0부터 시작합니다.
- `r`에서 물질을 확인하며 실리콘은 물질 3입니다. 계면 값은 점과 물질로
  선택하며 영역 번호나 컬럼 위치로 추측하지 않습니다.
- `s`의 species 순서에 따라 활성 As/P/Sb 코드 20/21/22의 합에서 활성 B 코드
  23을 뺍니다. 화학 농도나 코드 24로 대체하지 않습니다. 알 수 없는 species·물질,
  누락된 활성 도핑 컬럼은 거부합니다.
- 실리콘 삼각형에서 농도를 선형 보간하며 외삽하지 않습니다. 영역 누락,
  퇴화·중복 셀, 값이 충돌하는 겹침, 잘못된 NMOS 접촉·기판·채널 극성, 비유한
  숫자는 거부합니다. 총 주입량 보존 리매핑이나 범용 메시 검사기는 아닙니다.
- B.9305 2D 실리콘·산화막·폴리 파일만 지원합니다. 1 MiB, 4000점, 8000삼각형
  제한이 있으며 다른 버전과 1D 공정 프로파일은 별도 어댑터가 필요합니다.

형식 근거는 [기록된 원본 리비전의 STR 설명](https://github.com/ypooh2042/tcad-webapp/blob/13bce4a9daba5796ceee633fb8cd0c870465f766/SUPREM4GS/STR_FILE_FORMAT.md),
메시 API는 [DEVSIM 공식 안내](https://devsim.net/meshing.html)를 참고합니다.
파서·메시·덱 생성기는 저장소 코드이며 SUPREM 바이너리, 원본 예제 덱, 패치 묶음을
복사하지 않습니다. 별도 설치한 DEVSIM 헬퍼는 Apache-2.0이며 SUPREM 사용·재배포
권한은 별도 검토 대상입니다.

## 재실행과 남은 작업

2D JSON을 저장한 뒤 버전 고정 환경에서 다시 계산합니다.

```bash
python -m backend.app.experimental.replay opentcad-mos-result.json
python -m backend.app.experimental.replay opentcad-mos-result.json --suprem-structure /absolute/path/process.str
```

기록 해시, 입력, 템플릿 소스 해시, 솔버 버전, 공정 파일 해시, 연결성과 수치
필드를 비교합니다. 상대 허용 오차는 1e-7이고 절대 허용 오차도 출력하며 I-V
전류는 1e-12 A입니다. 바이트 일치는 별도로 표시하고 서로 다른 네이티브 희소
솔버 사이에서 보장하지 않습니다. 해시는 서명이나 수치 승인 인증서가 아닙니다.

플랫폼별 SUPREM 자격 검증, 전체 공정 형상과 접촉 전달, 보정된 MOS 수치 기준,
제품 승인 솔버 이미지·라이선스, M3 런타임 자격, 실제 전원 차단 검증은 남아
있습니다. 기존 증거 승인 상태와 OpenTCAD OG 이미지는 변경하지 않습니다.
