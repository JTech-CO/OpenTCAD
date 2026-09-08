# SUPREM 원본 메시와 전극

[English](../en/process-mesh.md) · [설치와 모델](mos-process.md)

실험용 `suprem-mesh` 모드는 공정의 실리콘·산화막 삼각형, 계면, 활성 노드 도핑을
유지합니다. 기본 직사각형 소자에 보간하지 않습니다. 소스·드레인·기판·게이트는
정확한 STR SHA-256에 묶인 별도 JSON의 외곽 경계로 명시합니다.

## 지원 공정 생성 및 연결

[공정 안내](mos-process.md)의 구성을 갖춘 신뢰할 수 있는 기존 SUPREM 이미지를
사용합니다. 이미지를 내려받거나 재배포하지 않습니다. Python과 Podman이 동작하는
환경에서 저장소 디렉토리를 기준으로 실행합니다.

```bash
python -m backend.app.experimental.suprem_container --enable-experimental-suprem --runtime podman --image sha256:YOUR_64_HEX_LOCAL_IMAGE_ID --output /absolute/new-run --gate-oxide-nm 10
python -m backend.app.experimental.process_mesh /absolute/new-run/process.str --output /absolute/new-run/contacts.json --gate-length 1 --oxide-nm 10
```

`--gate-oxide-nm`은 주입·열처리 후 유전체를 **증착하고 식각**합니다. 열 산화를
의미하지 않습니다. 생략하면 기존 실리콘-only 덱을 유지합니다.
`--lateral-refinement 2`는 초기 x 간격만 절반으로 줄이고 y 간격은 유지합니다.
소자 해석만 세분화하는 것이 아니라 더 촘촘한 메시에서 공정을 다시 실행합니다.
STR 점·삼각형 개수 제한은 유지되므로 큰 사례는 실패할 수 있습니다. 명시적
네이티브 SUPREM CLI에서도 같은 옵션을 지원합니다.

접촉 생성기는 선언된 직사각형 덱 전용이며 범용 전극 추론기가 아닙니다.
게이트 바깥 실리콘 상단, 실리콘 뒷면, 산화막 상단을 선택하고 누락되거나
모호한 경계는 거부합니다. 다른 덱에 적용하기 전 결과를 검토해야 합니다.
이 CLI는 기존 공정 디렉토리나 접촉 파일을 덮어쓰지 않습니다.

현재 Windows의 Debian/Podman 환경에서는 공정 명령의 `python` 대신
`wsl.exe -d Debian -- python3`를 사용합니다. 이후 접촉 생성기와 실험실은
Windows의 버전 고정 DEVSIM 환경에서 실행합니다. 산출물은 로컬에만 남습니다.
앞서 관측한 참조 이미지도 제품 승인 릴리스가 아닙니다.

```bash
npm run local:lab -- --suprem-structure /absolute/new-run/process.str --suprem-contacts /absolute/new-run/contacts.json
```

2D 화면에서 **SUPREM 원본 메시·접촉**을 선택합니다. 소자 폭, 게이트 전압,
드레인 전압만 편집할 수 있습니다. 형상·도핑·메시 간격은 공정 파일에서 읽습니다.
입력 기록의 호환성을 위해 JSON에 템플릿 전용 필드가 남지만 이 모드에서는
사용하지 않습니다. 지도에는 실제 좌표와 지정한 전극 선분을 표시하며 x/y 축은
별도로 배율을 정합니다. 서버는 시작 시 두 파일을 스냅샷으로 읽고 HTTP로
파일 경로나 덱을 받지 않습니다. 구조 없이 접촉 파일만 지정하면 시작을 거부합니다.

## 접촉 계약과 안전 검사

정확한 필드는 `format: "opentcad-suprem-contacts"`, `schemaVersion: 1`,
`sourceSha256`, `contacts`입니다. contacts에는 source, drain, body, gate만
허용하며 각각 정수 STR `region` ID와 `edges` 배열을 가집니다. 선분은 원래의
**1부터 시작하는 STR 점 ID** 쌍입니다. DEVSIM 노드 번호가 아닙니다. 기존 선분으로
이루어진 곡선 경계도 지정할 수 있지만 선분을 분할하지는 않습니다.

연결된 실리콘 1영역과 산화막 1영역, 정합된 공통 계면을 지원합니다. 지원하지
않는 물질·추가 영역, 중복 좌표·삼각형, 접히거나 퇴화한 셀, 비다양체 선분,
교차, T 접합, 끊어진 영역·계면을 거부합니다. 각 접촉은 올바른 재료의 외곽에서
연결된 열린 선분 사슬이어야 합니다. 접촉끼리 또는 접촉과 실리콘·산화막 계면이
노드를 공유할 수 없습니다. 소스·드레인의 순 도핑은 양수, 기판은 음수여야 하고
계면 일부는 p형이어야 합니다. 이는 구조 검사이지 보정된 MOS 소자의 물리적
적합성 보증은 아닙니다.

원본 삼각형을 유지하며 DEVSIM에서 μm를 cm로 바꾸고, 원래 실리콘 노드에 보간
없이 도핑을 할당합니다. 전위 연속 조건은 가져온 계면에 연결합니다. 산화막 상단은
기존 +0.45 V 오프셋의 이상적인 금속 경계이며 폴리실리콘을 해석하는 것은 아닙니다.
결과 검사에서는 반올림 수준을 고려해 삼각형 좌표·연결성과 영역 면적·개수를
비교합니다. 구조·접촉 파일·메시 해시를 기록하며 M3 승인 조건, 솔버 라이선스
경계, OG 이미지는 변경하지 않습니다.

## 재실행과 검증

```bash
python -m backend.app.experimental.replay opentcad-mos-result.json --suprem-structure /absolute/new-run/process.str --suprem-contacts /absolute/new-run/contacts.json
npm run test:mvp:solver
```

같은 구조·접촉 해시, 템플릿 소스 해시, 입력과 솔버 버전이 필요합니다.
수치·형상·접촉을 비교하므로 전극 배치를 바꾸고 이전 결과를 재사용할 수 없습니다.
오래된 결과의 엄격한 재실행에는 해당 소스 리비전이 필요합니다.

네이티브 테스트는 동등한 합성 템플릿·원본 메시 해석, 게이트 응답, 정확한 노드
도핑 전달, 반복 재현과 잘못된 접촉 거부를 Windows·macOS·Linux에서 검사합니다.
합성 파일은 실제 SUPREM 실행 증거가 아닙니다. 별도의 실제 Podman SUPREM 관측은
실리콘 3,400개·산화막 80개 삼각형을 유지하며 VG=1 V, VD=0.1 V, W=10 μm에서
약 115.762 μA를 계산했습니다. 공정 메시의 가로 세분화 결과는 115.528 μA로
약 0.203% 차이였습니다. 공정 이산화 변화까지 포함한 비교이며 일반 오차 한계나
보정된 수치 corpus 승인은 아닙니다.
[로컬 관측 기록](../../validation/experimental/process-mesh-observation.json)에서
소스·결과 해시와 인증 HTTP, 재실행, 프런트엔드 결과 검증 기록을 확인할 수 있습니다.

다중 실리콘·산화막 영역, 폴리·금속·질화막 적층, 범용 전극 추론, 메시 복구,
제품 승인 공정 정확도는 남아 있습니다. GitHub Pages는 네이티브 솔버를 실행하지
않으며 공개 페이지 반영에는 별도 `main` 병합·배포가 필요합니다.
