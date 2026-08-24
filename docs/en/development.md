# Development

[한국어](../ko/development.md)

## Prerequisites

- Node.js 22 LTS or 24 LTS
- npm 10 or newer
- Python 3.12 through 3.14 for the M2 contract tests
- Git

No container runtime, Python service, external database server, or solver is required. Python runs only the dependency-free M2 contract tests; SQLite candidate tests use the standard library and isolated temporary files.

## Setup and commands

```bash
npm install
npm run dev
```

The development server uses Vite. Production checks are:

```bash
npm run lint
npm run test
npm run check:m2
npm run build
```

Use `npm run preview` to serve the production bundle on `127.0.0.1`. The build uses relative asset URLs so a single artifact works under the GitHub repository subpath and on an ordinary local static server.

## Frontend rules

- Every user-visible string belongs in `frontend/src/i18n.ts` and must exist in both English and Korean.
- User typing state stays a string until explicit validation; do not coerce intermediate numeric input.
- Stable internal IDs are never derived from editable labels.
- Loading, empty, running, complete, partial, skipped, and failed states must remain visually and textually distinct.
- Color is supplementary. Status also needs text, shape, or icon-independent wording.
- Static reference data must be visibly labelled and must not use words such as “validated,” “converged,” or “solver result.”
- Store only device-local preferences, such as locale, in browser storage.

## Adding local-engine work

Do not add a direct `docker`, `podman`, shell, or subprocess call from the frontend or API. Runtime implementation starts with a typed `RuntimeBackend` contract and policy tests, followed by real Docker and rootless Podman evidence. The sandbox broker is the only component allowed to reach an engine socket.

Any runtime, numerical, data-migration, or distribution change must follow `02_CODEX_HARNESS_KR.md`, including its issue-intake report, risk level, tests-first boundary, security/numerical delta, and rollback evidence.

## Documentation parity

English and Korean documents are paired by path:

```text
docs/en/<name>.md
docs/ko/<name>.md
```

A functional or operational documentation change is incomplete until both files describe the same contract. The detailed original planning bundle remains Korean source material; new maintained product documentation is bilingual.
