# Third-party licenses / 제3자 라이선스

This inventory covers the direct JavaScript dependencies in the OpenTCAD foundation release. Exact dependency resolution is recorded in `package-lock.json`. Transitive dependency notices and a machine-readable SBOM remain a release-hardening gate.

이 목록은 OpenTCAD 기반 릴리스의 직접 JavaScript 의존성을 다룹니다. 정확한 의존성 해석 결과는 `package-lock.json`에 기록합니다. 전이 의존성 고지와 기계 판독 가능한 SBOM은 릴리스 강화 단계의 필수 게이트입니다.

## Runtime bundle / 실행 번들

| Component | Locked version | License | Project |
|---|---:|---|---|
| React | 19.2.8 | MIT | https://github.com/facebook/react |
| React DOM | 19.2.8 | MIT | https://github.com/facebook/react |

## Build and test toolchain / 빌드·테스트 도구

| Component | Locked version | License | Project |
|---|---:|---|---|
| Vite | 7.3.6 | MIT | https://github.com/vitejs/vite |
| @vitejs/plugin-react | 5.2.0 | MIT | https://github.com/vitejs/vite-plugin-react |
| TypeScript | 5.9.3 | Apache-2.0 | https://github.com/microsoft/TypeScript |
| Vitest / @vitest/coverage-v8 | 4.1.11 | MIT | https://github.com/vitest-dev/vitest |
| Testing Library packages | lockfile versions | MIT | https://github.com/testing-library |
| jsdom | 27.4.0 | MIT | https://github.com/jsdom/jsdom |
| oxlint | 1.79.0 | MIT | https://github.com/oxc-project/oxc |
| DefinitelyTyped type packages | lockfile versions | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |

## Solver boundary / 솔버 경계

The foundation release includes no SUPREM-IV.GS, Gmsh, or DEVSIM source or binary. Their terms are not covered by the OpenTCAD MIT License. Any future image or installer must add component-specific source provenance, copyright, complete license text, inclusion decision, and redistribution approval before publication.

기반 릴리스에는 SUPREM-IV.GS, Gmsh, DEVSIM 소스나 바이너리를 포함하지 않습니다. 이들의 조건은 OpenTCAD MIT 라이선스의 적용 대상이 아닙니다. 향후 이미지 또는 installer를 게시하려면 구성요소별 소스 출처, 저작권, 전체 라이선스 원문, 포함 결정, 재배포 승인을 먼저 추가해야 합니다.
